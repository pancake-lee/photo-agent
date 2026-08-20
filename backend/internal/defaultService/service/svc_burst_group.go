package service

import (
	"bufio"
	"context"
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

	"github.com/pancake-lee/pgo/pkg/papp"
	"github.com/pancake-lee/pgo/pkg/plogger"
)

// --------------------------------------------------
// burstGroupManager 连拍分组重算的运行时状态（模式与 vlmQueueManager 一致）
type burstGroupManager struct {
	mu         sync.Mutex
	running    bool
	processed  int32
	total      int32
	groupCount int32
}

func (m *burstGroupManager) snapshot() *api.GetBurstGroupsStatusResponse {
	m.mu.Lock()
	defer m.mu.Unlock()
	return &api.GetBurstGroupsStatusResponse{
		Running:    m.running,
		Processed:  m.processed,
		Total:      m.total,
		GroupCount: m.groupCount,
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
	m.groupCount = 0
	return true
}

func (m *burstGroupManager) stop(groupCount int32) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.running = false
	m.groupCount = groupCount
}

func (m *burstGroupManager) setProcessed(n int32) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.processed = n
}

func (m *burstGroupManager) setGroupCount(n int32) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.groupCount = n
}

// 全局连拍分组管理器实例
var burstGroups = &burstGroupManager{}

// --------------------------------------------------
// PhotoService 的连拍分组 rpc 实现（挂在 PhotoServer 上，路由由其 Reg 统一注册）

// RebuildBurstGroups 触发连拍分组全量重算（异步，后台 goroutine 执行）。
func (s *PhotoServer) RebuildBurstGroups(
	_ctx context.Context, _ *api.Empty,
) (*api.RebuildBurstGroupsResponse, error) {
	ctx := papp.NewAppCtx(_ctx)

	photos, err := data.PhotoDAO.GetBurstPhotos(ctx)
	if err != nil {
		return nil, ctx.Log.LogErr(err)
	}

	if !burstGroups.start(int32(len(photos))) {
		return &api.RebuildBurstGroupsResponse{Status: "already_running"}, nil
	}

	go runBurstRebuild(photos)
	return &api.RebuildBurstGroupsResponse{Status: "running"}, nil
}

// GetBurstGroupsStatus 轮询重算进度；未在跑时返回当前库内组数。
func (s *PhotoServer) GetBurstGroupsStatus(
	_ctx context.Context, _ *api.Empty,
) (*api.GetBurstGroupsStatusResponse, error) {
	ctx := papp.NewAppCtx(_ctx)

	snap := burstGroups.snapshot()
	if !snap.Running {
		n, err := data.PhotoGroupDAO.CountPhotoGroups(ctx)
		if err != nil {
			return nil, ctx.Log.LogErr(err)
		}
		snap.GroupCount = int32(n)
	}
	return snap, nil
}

// --------------------------------------------------
// 重算主流程
// --------------------------------------------------

// runBurstRebuild 后台执行全量重算：清空旧分组 → 时间窗分割 → 哈希/SSIM 验证 → 写库。
func runBurstRebuild(photos []*data.PhotoDO) {
	groupCount, err := rebuildBurstGroups(photos)
	if err != nil {
		plogger.Errorf("burst groups rebuild failed: %v", err)
	}
	burstGroups.stop(groupCount)
	plogger.Infof("burst groups rebuild done: %d groups from %d photos", groupCount, len(photos))
}

func rebuildBurstGroups(photos []*data.PhotoDO) (int32, error) {
	ctx := papp.NewAppCtx(context.Background())

	// 1. 幂等清理：先清空全部分组数据
	if err := data.PhotoGroupDAO.ClearAllBurstGroups(ctx); err != nil {
		return 0, err
	}

	// 2. 计算每张照片的 9x8 灰度矩阵（dHash 与 SSIM 共用）
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

	// 3. 时间窗分割 + 相似度验证，产出最终分组
	groups := splitBurstGroups(list)

	// 4. 组内 ≥2 张才建组记录
	saved := int32(0)
	for _, g := range groups {
		if len(g) < 2 {
			continue
		}
		if err := saveBurstGroup(ctx, g); err != nil {
			return saved, err
		}
		saved++
		burstGroups.setGroupCount(saved)
	}
	return saved, nil
}

// saveBurstGroup 写入一条组记录并回填组内照片的 burst_group_id。
func saveBurstGroup(ctx *papp.AppCtx, group []burstPhotoInfo) error {
	first := group[0].photo
	last := group[len(group)-1].photo

	groupID := fmt.Sprintf("burst_%s", first.ID[:8])
	hashMax := 0
	for _, m := range group {
		if m.hashDist > hashMax {
			hashMax = m.hashDist
		}
	}

	do := &data.PhotoGroupDO{
		ID:           groupID,
		CoverPhotoID: first.ID, // 封面约定为组内 shot_at 最早一张
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
	return data.PhotoDAO.SetPhotosBurstGroup(ctx, idList, groupID)
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
func splitBurstGroups(list []burstPhotoInfo) [][]burstPhotoInfo {
	candidates := splitByTimeWindow(list, time.Duration(conf.C.Burst.TimeWindowSec)*time.Second)
	groups := make([][]burstPhotoInfo, 0, len(candidates))
	for _, cand := range candidates {
		groups = append(groups, splitBySimilarity(cand)...)
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
func splitBySimilarity(cand []burstPhotoInfo) [][]burstPhotoInfo {
	bc := conf.C.Burst
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
		case dist <= bc.SsimGrayMin:
			// 明显相似，直接同组（距离小于灰区下界必然 ≤ HashThreshold 的默认口径）
			same = dist <= bc.HashThreshold
		case dist <= bc.SsimGrayMax:
			// 灰区：SSIM 二次验证
			same = calcSSIM(prev.gray, item.gray) >= bc.SsimThreshold
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
