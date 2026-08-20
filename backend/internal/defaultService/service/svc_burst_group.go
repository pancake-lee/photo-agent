package service

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"backend/internal/defaultService/conf"
	"backend/internal/defaultService/data"
	"backend/internal/pkg/api"
	"backend/internal/pkg/perr"

	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/plogger"
)

// --------------------------------------------------
// 连拍分组阈值（精细/模糊两档）
//
// 运行期生效值存 app_settings 表（key = burstConfigKey，JSON 值），
// 由网页设置页编辑保存；表内无记录时用配置文件默认值。

const burstConfigKey = "burst_config"

// 档位取值，proto 与存储共用同一套字段口径
const (
	BurstProfileFine   = "fine"
	BurstProfileCoarse = "coarse"
)

type burstParams struct {
	TimeWindowSec int     `json:"time_window_sec"`
	HashThreshold int     `json:"hash_threshold"`
	SsimThreshold float64 `json:"ssim_threshold"`
	SsimGrayMin   int     `json:"ssim_gray_min"`
	SsimGrayMax   int     `json:"ssim_gray_max"`
}

type burstConfig struct {
	Fine   burstParams `json:"fine"`
	Coarse burstParams `json:"coarse"`
}

// confBurstConfig 配置文件默认的两档阈值（DB 无记录时的初始值）。
func confBurstConfig() burstConfig {
	return burstConfig{
		Fine: burstParams{
			TimeWindowSec: conf.C.Burst.Fine.TimeWindowSec,
			HashThreshold: conf.C.Burst.Fine.HashThreshold,
			SsimThreshold: conf.C.Burst.Fine.SsimThreshold,
			SsimGrayMin:   conf.C.Burst.Fine.SsimGrayMin,
			SsimGrayMax:   conf.C.Burst.Fine.SsimGrayMax,
		},
		Coarse: burstParams{
			TimeWindowSec: conf.C.Burst.Coarse.TimeWindowSec,
			HashThreshold: conf.C.Burst.Coarse.HashThreshold,
			SsimThreshold: conf.C.Burst.Coarse.SsimThreshold,
			SsimGrayMin:   conf.C.Burst.Coarse.SsimGrayMin,
			SsimGrayMax:   conf.C.Burst.Coarse.SsimGrayMax,
		},
	}
}

// loadBurstConfig 读取生效的两档阈值：app_settings 优先，无记录回退配置文件默认值。
func loadBurstConfig(ctx *papp.AppCtx) (burstConfig, error) {
	raw, err := data.AppSettingDAO.GetAppSetting(ctx, burstConfigKey)
	if err != nil {
		return burstConfig{}, err
	}
	if raw == "" {
		return confBurstConfig(), nil
	}
	var cfg burstConfig
	if err := json.Unmarshal([]byte(raw), &cfg); err != nil {
		return burstConfig{}, fmt.Errorf("parse burst config failed: %w", err)
	}
	return cfg, nil
}

func (p burstParams) toProto() *api.BurstProfileConfig {
	return &api.BurstProfileConfig{
		TimeWindowSec: int32(p.TimeWindowSec),
		HashThreshold: int32(p.HashThreshold),
		SsimThreshold: p.SsimThreshold,
		SsimGrayMin:   int32(p.SsimGrayMin),
		SsimGrayMax:   int32(p.SsimGrayMax),
	}
}

func burstParamsFromProto(c *api.BurstProfileConfig) burstParams {
	if c == nil {
		return burstParams{}
	}
	return burstParams{
		TimeWindowSec: int(c.TimeWindowSec),
		HashThreshold: int(c.HashThreshold),
		SsimThreshold: c.SsimThreshold,
		SsimGrayMin:   int(c.SsimGrayMin),
		SsimGrayMax:   int(c.SsimGrayMax),
	}
}

// validateBurstConfig 保存前的合法性校验，拒绝明显越界的参数。
func validateBurstConfig(cfg burstConfig) error {
	for name, p := range map[string]burstParams{BurstProfileFine: cfg.Fine, BurstProfileCoarse: cfg.Coarse} {
		switch {
		case p.TimeWindowSec < 1 || p.TimeWindowSec > 3600:
			return fmt.Errorf("%s time_window_sec out of range: %d", name, p.TimeWindowSec)
		case p.HashThreshold < 0 || p.HashThreshold > 64:
			return fmt.Errorf("%s hash_threshold out of range: %d", name, p.HashThreshold)
		case p.SsimThreshold < 0 || p.SsimThreshold > 1:
			return fmt.Errorf("%s ssim_threshold out of range: %f", name, p.SsimThreshold)
		case p.SsimGrayMin < 0 || p.SsimGrayMax > 64 || p.SsimGrayMin > p.SsimGrayMax:
			return fmt.Errorf("%s ssim gray zone invalid: [%d, %d]", name, p.SsimGrayMin, p.SsimGrayMax)
		}
	}
	return nil
}

// --------------------------------------------------
// burstGroupManager 连拍分组重算的运行时状态（模式与 vlmQueueManager 一致）
type burstGroupManager struct {
	mu               sync.Mutex
	running          bool
	processed        int32
	total            int32
	fineGroupCount   int32
	coarseGroupCount int32
}

func (m *burstGroupManager) snapshot() *api.GetBurstGroupsStatusResponse {
	m.mu.Lock()
	defer m.mu.Unlock()
	return &api.GetBurstGroupsStatusResponse{
		Running:          m.running,
		Processed:        m.processed,
		Total:            m.total,
		GroupCount:       m.fineGroupCount,
		CoarseGroupCount: m.coarseGroupCount,
	}
}

func (m *burstGroupManager) isRunning() bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.running
}

// start 返回 false 表示已在运行中。
func (m *burstGroupManager) start(total int32) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.running {
		return false
	}
	m.running = true
	m.processed = 0
	m.total = total
	m.fineGroupCount = 0
	m.coarseGroupCount = 0
	return true
}

func (m *burstGroupManager) stop(fineCount, coarseCount int32) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.running = false
	m.fineGroupCount = fineCount
	m.coarseGroupCount = coarseCount
}

func (m *burstGroupManager) setProcessed(n int32) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.processed = n
}

func (m *burstGroupManager) setGroupCount(profile string, n int32) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if profile == BurstProfileCoarse {
		m.coarseGroupCount = n
	} else {
		m.fineGroupCount = n
	}
}

// 全局连拍分组管理器实例
var burstGroups = &burstGroupManager{}

// --------------------------------------------------
// PhotoService 的连拍分组 rpc 实现（挂在 PhotoServer 上，路由由其 Reg 统一注册）

// RebuildBurstGroups 触发连拍分组全量重算（异步，后台 goroutine 执行，一次算两档）。
func (s *PhotoServer) RebuildBurstGroups(
	_ctx context.Context, _ *api.Empty,
) (*api.RebuildBurstGroupsResponse, error) {
	ctx := papp.NewAppCtx(_ctx)

	if burstGroups.isRunning() {
		return &api.RebuildBurstGroupsResponse{Status: "already_running"}, nil
	}

	photos, err := data.PhotoDAO.GetBurstPhotos(ctx)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	cfg, err := loadBurstConfig(ctx)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	if !burstGroups.start(int32(len(photos))) {
		return &api.RebuildBurstGroupsResponse{Status: "already_running"}, nil
	}

	go runBurstRebuild(photos, cfg)
	return &api.RebuildBurstGroupsResponse{Status: "running"}, nil
}

// GetBurstGroupsStatus 轮询重算进度；未在跑时返回当前库内两档组数。
func (s *PhotoServer) GetBurstGroupsStatus(
	_ctx context.Context, _ *api.Empty,
) (*api.GetBurstGroupsStatusResponse, error) {
	ctx := papp.NewAppCtx(_ctx)

	snap := burstGroups.snapshot()
	if !snap.Running {
		fine, err := data.PhotoGroupDAO.CountPhotoGroups(ctx, BurstProfileFine)
		if err != nil {
			return nil, ctx.Log.LogErr(err)
		}
		coarse, err := data.PhotoGroupDAO.CountPhotoGroups(ctx, BurstProfileCoarse)
		if err != nil {
			return nil, ctx.Log.LogErr(err)
		}
		snap.GroupCount = int32(fine)
		snap.CoarseGroupCount = int32(coarse)
	}
	return snap, nil
}

// GetBurstGroupsConfig 返回当前生效的两档阈值。
func (s *PhotoServer) GetBurstGroupsConfig(
	_ctx context.Context, _ *api.Empty,
) (*api.GetBurstGroupsConfigResponse, error) {
	ctx := papp.NewAppCtx(_ctx)

	cfg, err := loadBurstConfig(ctx)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	return &api.GetBurstGroupsConfigResponse{
		Fine:   cfg.Fine.toProto(),
		Coarse: cfg.Coarse.toProto(),
	}, nil
}

// UpdateBurstGroupsConfig 保存两档阈值到 app_settings，下次 rebuild 生效。
func (s *PhotoServer) UpdateBurstGroupsConfig(
	_ctx context.Context, req *api.UpdateBurstGroupsConfigRequest,
) (*api.Empty, error) {
	ctx := papp.NewAppCtx(_ctx)

	cfg := burstConfig{
		Fine:   burstParamsFromProto(req.Fine),
		Coarse: burstParamsFromProto(req.Coarse),
	}
	if err := validateBurstConfig(cfg); err != nil {
		return nil, ctx.Log.LogErr(perr.ErrParamInvalid)
	}

	raw, err := json.Marshal(cfg)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	if err := data.AppSettingDAO.SetAppSetting(ctx, burstConfigKey, string(raw)); err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	return &api.Empty{}, nil
}

// SetBurstGroupCover 将组内某张照片设为封面。
func (s *PhotoServer) SetBurstGroupCover(
	_ctx context.Context, req *api.SetBurstGroupCoverRequest,
) (*api.Empty, error) {
	ctx := papp.NewAppCtx(_ctx)

	if req.GroupId == "" || req.PhotoId == "" {
		return nil, ctx.Log.LogErr(perr.ErrParamInvalid)
	}

	group, err := data.PhotoGroupDAO.GetByID(ctx, req.GroupId)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	photo, err := data.PhotoDAO.GetByID(ctx, req.PhotoId)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	// 校验照片确属该组（表间无外键，一致性由本层保证）
	memberOf := photo.BurstGroupID
	if group.Profile == BurstProfileCoarse {
		memberOf = photo.BurstGroupCoarseID
	}
	if memberOf != group.ID {
		return nil, ctx.Log.LogErr(perr.ErrParamInvalid)
	}

	if err := data.PhotoGroupDAO.UpdateCoverPhotoID(ctx, group.ID, photo.ID); err != nil {
		return nil, ctx.Log.LogErr(err)
	}
	return &api.Empty{}, nil
}

// --------------------------------------------------
// 重算主流程
// --------------------------------------------------

// runBurstRebuild 后台执行全量重算：清空旧分组 → 灰度矩阵 → 两档分别分组 → 写库。
func runBurstRebuild(photos []*data.PhotoDO, cfg burstConfig) {
	fineCount, coarseCount, err := rebuildBurstGroups(photos, cfg)
	if err != nil {
		plogger.Errorf("burst groups rebuild failed: %v", err)
	}
	burstGroups.stop(fineCount, coarseCount)
	plogger.Infof("burst groups rebuild done: fine %d / coarse %d groups from %d photos",
		fineCount, coarseCount, len(photos))
}

func rebuildBurstGroups(photos []*data.PhotoDO, cfg burstConfig) (int32, int32, error) {
	ctx := papp.NewAppCtx(context.Background())

	// 1. 幂等清理：先清空全部分组数据（两档）
	if err := data.PhotoGroupDAO.ClearAllBurstGroups(ctx); err != nil {
		return 0, 0, err
	}

	// 2. 计算每张照片的 9x8 灰度矩阵（两档共用，只算一次）
	list := make([]burstPhotoInfo, len(photos))
	for i, p := range photos {
		list[i].photo = p
		gray, err := loadGrayMatrix(filepath.Join(conf.C.Storage.PhotoPath, p.FilePath))
		if err != nil {
			// 单张失败不中断整体：该照片不参与哈希/SSIM 判定，仅按时间窗归组
			plogger.Warnf("burst: load gray matrix failed %s: %v", p.FilePath, err)
		} else {
			list[i].gray = gray
			list[i].valid = true
		}
		burstGroups.setProcessed(int32(i + 1))
	}

	// 3. 两档分别分组并写库（灰度数据复用，算法按各自阈值跑）
	fineSaved, err := rebuildProfile(ctx, list, BurstProfileFine, cfg.Fine)
	if err != nil {
		return fineSaved, 0, err
	}
	coarseSaved, err := rebuildProfile(ctx, list, BurstProfileCoarse, cfg.Coarse)
	if err != nil {
		return fineSaved, coarseSaved, err
	}
	return fineSaved, coarseSaved, nil
}

// rebuildProfile 按单档阈值分组并写库，返回建档数量。
func rebuildProfile(ctx *papp.AppCtx, list []burstPhotoInfo, profile string, bp burstParams) (int32, error) {
	// hashDist 是上一次档位运行留下的，重算前清零
	for i := range list {
		list[i].hashDist = 0
	}

	saved := int32(0)
	for _, g := range splitBurstGroups(list, bp) {
		if len(g) < 2 {
			continue
		}
		if err := saveBurstGroup(ctx, g, profile); err != nil {
			return saved, err
		}
		saved++
		burstGroups.setGroupCount(profile, saved)
	}
	return saved, nil
}

// saveBurstGroup 写入一条组记录并回填组内照片的分组 id。
func saveBurstGroup(ctx *papp.AppCtx, group []burstPhotoInfo, profile string) error {
	first := group[0].photo
	last := group[len(group)-1].photo

	groupID := fmt.Sprintf("burst_%s_%s", profile, first.ID[:8])
	hashMax := 0
	for _, m := range group {
		if m.hashDist > hashMax {
			hashMax = m.hashDist
		}
	}

	do := &data.PhotoGroupDO{
		ID:           groupID,
		CoverPhotoID: first.ID, // 封面约定为组内 shot_at 最早一张
		Profile:      profile,
		PhotoCount:   int32(len(group)),
		TimeStart:    first.ShotAt,
		TimeEnd:      last.ShotAt,
		HashMax:      int32(hashMax),
		CreatedAt:    time.Now(),
	}
	if err := data.PhotoGroupDAO.Add(ctx, do); err != nil {
		return err
	}

	idList := make([]string, len(group))
	for i, m := range group {
		idList[i] = m.photo.ID
	}
	return data.PhotoDAO.SetPhotosBurstGroup(ctx, idList, groupID, profile)
}

// --------------------------------------------------
// 分组算法（纯函数，单测覆盖）
// --------------------------------------------------

// burstPhotoInfo 分组算法的单张照片输入。
// gray 为 9x8=72 个灰度值（行优先），valid 表示灰度数据可用。
// hashDist 为与组内前一张的 dHash 汉明距离（写库时取组内最大值）。
type burstPhotoInfo struct {
	photo    *data.PhotoDO
	gray     []float64
	valid    bool
	hashDist int
}

// splitBurstGroups 三段式分组：时间窗分割 → 哈希切分 → SSIM 灰区判定。
func splitBurstGroups(list []burstPhotoInfo, bp burstParams) [][]burstPhotoInfo {
	candidates := splitByTimeWindow(list, time.Duration(bp.TimeWindowSec)*time.Second)
	groups := make([][]burstPhotoInfo, 0, len(candidates))
	for _, cand := range candidates {
		groups = append(groups, splitBySimilarity(cand, bp)...)
	}
	return groups
}

// splitByTimeWindow 按相邻拍摄间隔分割候选组，间隔 ≤ window 进同组。
func splitByTimeWindow(list []burstPhotoInfo, window time.Duration) [][]burstPhotoInfo {
	groups := [][]burstPhotoInfo{}
	cur := []burstPhotoInfo{}
	for i, item := range list {
		if i > 0 {
			gap := item.photo.ShotAt.Sub(list[i-1].photo.ShotAt)
			if gap > window {
				groups = append(groups, cur)
				cur = []burstPhotoInfo{}
			}
		}
		cur = append(cur, item)
	}
	if len(cur) > 0 {
		groups = append(groups, cur)
	}
	return groups
}

// splitBySimilarity 候选组内逐对验证：相邻 dHash 距离判定，灰区用 SSIM 二次确认。
// 任一相邻对不相似则在该处切分（局部构图突变不否定前后两段）。
func splitBySimilarity(cand []burstPhotoInfo, bp burstParams) [][]burstPhotoInfo {
	groups := [][]burstPhotoInfo{}
	cur := []burstPhotoInfo{}

	for i, item := range cand {
		if i == 0 {
			cur = append(cur, item)
			continue
		}
		prev := cand[i-1]

		// 灰度数据不可用的照片对，无法做内容验证，按时间窗结论保留同组
		if !prev.valid || !item.valid {
			cur = append(cur, item)
			continue
		}

		dist := hammingDist(dHashOf(prev.gray), dHashOf(item.gray))
		same := false
		switch {
		case dist <= bp.SsimGrayMin:
			// 明显相似，直接同组（距离小于灰区下界必然 ≤ HashThreshold 的默认口径）
			same = dist <= bp.HashThreshold
		case dist <= bp.SsimGrayMax:
			// 灰区：SSIM 二次验证
			same = calcSSIM(prev.gray, item.gray) >= bp.SsimThreshold
		default:
			// 距离超过灰区上界，明显不同
			same = false
		}

		if same {
			item.hashDist = dist
			cur = append(cur, item)
		} else {
			groups = append(groups, cur)
			cur = []burstPhotoInfo{}
			cur = append(cur, item)
		}
	}
	if len(cur) > 0 {
		groups = append(groups, cur)
	}
	return groups
}

// dHashOf 由 9x8 灰度矩阵（行优先）计算 64bit dHash：
// 每行比较相邻像素（左 > 右 记 1），8 行 × 8 位。
func dHashOf(gray []float64) uint64 {
	if len(gray) != burstGrayW*burstGrayH {
		return 0
	}
	var h uint64
	bit := 0
	for y := 0; y < burstGrayH; y++ {
		for x := 0; x < burstGrayW-1; x++ {
			if gray[y*burstGrayW+x] > gray[y*burstGrayW+x+1] {
				h |= 1 << bit
			}
			bit++
		}
	}
	return h
}

// hammingDist 计算两个 64bit 哈希的汉明距离。
func hammingDist(a, b uint64) int {
	return int(popcount64(a ^ b))
}

func popcount64(x uint64) int {
	n := 0
	for x != 0 {
		x &= x - 1
		n++
	}
	return n
}

// calcSSIM 在 9x8 灰度矩阵上计算 SSIM（结构相似性）。
// 矩阵太小不分子块，整图按全局统计计算（经典公式）：
// SSIM = ((2μxμy + C1)(2σxy + C2)) / ((μx²+μy²+C1)(σx²+σy²+C2))，C=(0.01L)², (0.03L)²
func calcSSIM(x, y []float64) float64 {
	if len(x) != burstGrayW*burstGrayH || len(y) != burstGrayW*burstGrayH {
		return 0
	}
	n := float64(len(x))

	var sx, sy float64
	for i := range x {
		sx += x[i]
		sy += y[i]
	}
	mx, my := sx/n, sy/n

	var vx, vy, cov float64
	for i := range x {
		dx, dy := x[i]-mx, y[i]-my
		vx += dx * dx
		vy += dy * dy
		cov += dx * dy
	}
	vx, vy, cov = vx/n, vy/n, cov/n

	const L = 255.0
	c1 := (0.01 * L) * (0.01 * L)
	c2 := (0.03 * L) * (0.03 * L)

	num := (2*mx*my + c1) * (2*cov + c2)
	den := (mx*mx + my*my + c1) * (vx + vy + c2)
	if den == 0 {
		return 1 // 两图全等（常数图）视作完全相似
	}
	return num / den
}

// --------------------------------------------------
// ImageMagick 灰度矩阵加载
// --------------------------------------------------

const (
	burstGrayW = 9
	burstGrayH = 8
)

// loadGrayMatrix 用 ImageMagick 将缩略图缩放为 9x8 灰度，解析 TXT 输出为 72 个灰度值（行优先）。
// dHash 与 SSIM 共用同一份矩阵，SSIM 无需再起 compare 进程。
func loadGrayMatrix(imgPath string) ([]float64, error) {
	cmd := exec.Command("convert", imgPath,
		"-resize", fmt.Sprintf("%dx%d!", burstGrayW, burstGrayH),
		"-colorspace", "gray", "txt:-")
	out, err := cmd.Output()
	if err != nil {
		if ee, ok := err.(*exec.ExitError); ok {
			return nil, fmt.Errorf("imagemagick convert failed: %w, stderr: %s", err, ee.Stderr)
		}
		return nil, fmt.Errorf("imagemagick convert failed: %w", err)
	}
	return parseGrayTxt(out)
}

// parseGrayTxt 解析 `convert ... txt:` 输出中的像素灰度值。
// 行格式：`x,y: (gray,gray,gray)  #XXXXXX  gray(nn%)`，取首个括号内的数值。
func parseGrayTxt(out []byte) ([]float64, error) {
	gray := make([]float64, burstGrayW*burstGrayH)
	filled := 0

	scanner := bufio.NewScanner(strings.NewReader(string(out)))
	for scanner.Scan() {
		line := scanner.Text()

		// 严格的 "x,y: (v,..." 前缀校验，跳过注释行与异常行
		colon := strings.IndexByte(line, ':')
		open := strings.IndexByte(line, '(')
		if colon <= 0 || open <= colon {
			continue
		}
		coords := strings.Split(line[:colon], ",")
		if len(coords) != 2 {
			continue
		}
		x, err1 := strconv.Atoi(strings.TrimSpace(coords[0]))
		y, err2 := strconv.Atoi(strings.TrimSpace(coords[1]))
		valStr := line[open+1:]
		if comma := strings.IndexByte(valStr, ','); comma > 0 {
			valStr = valStr[:comma]
		} else {
			continue
		}
		v, err3 := strconv.ParseFloat(valStr, 64)
		if err1 != nil || err2 != nil || err3 != nil {
			continue
		}
		if x < 0 || x >= burstGrayW || y < 0 || y >= burstGrayH {
			continue
		}
		gray[y*burstGrayW+x] = v
		filled++
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	if filled != burstGrayW*burstGrayH {
		return nil, fmt.Errorf("parse gray txt: got %d pixels, want %d", filled, burstGrayW*burstGrayH)
	}
	return gray, nil
}
