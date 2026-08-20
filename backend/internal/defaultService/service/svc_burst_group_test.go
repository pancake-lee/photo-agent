package service

import (
	"strconv"
	"testing"
	"time"

	"backend/internal/defaultService/conf"
	"backend/internal/defaultService/data"
)

// burstTestDefaults 测试用默认阈值（与 configs/config.yaml 模板一致）
func burstTestDefaults() {
	conf.C.Burst.TimeWindowSec = 5
	conf.C.Burst.HashThreshold = 10
	conf.C.Burst.SsimThreshold = 0.85
	conf.C.Burst.SsimGrayMin = 8
	conf.C.Burst.SsimGrayMax = 12
}

// mkBurstPhoto 构造测试照片：id 从 A/B/C... 编号，shotAt 递增。
func mkBurstPhoto(id byte, shotAt time.Time, gray []float64) burstPhotoInfo {
	return burstPhotoInfo{
		photo: &data.PhotoDO{
			ID:     string([]byte{id, id, id, id, id, id, id, id}),
			ShotAt: shotAt,
		},
		gray:  gray,
		valid: gray != nil,
	}
}

// flatGray 构造 9x8 全均匀灰度矩阵（可指定底灰度值）。
func flatGray(v float64) []float64 {
	g := make([]float64, burstGrayW*burstGrayH)
	for i := range g {
		g[i] = v
	}
	return g
}

// grayWithBits 在均匀灰度上翻转指定数量的相邻像素梯度，
// 用于构造与基准图汉明距离约等于 flipCount 的图。
func grayWithBits(base float64, flipCount int) []float64 {
	g := flatGray(base)
	// 全均匀图 dHash 全 0；把前 flipCount 个位置的像素改成明暗交替，
	// 每处产生 2 个梯度位翻转（左右两个比较对），近似控制距离
	for i := 0; i < flipCount*2 && i < len(g); i++ {
		if i%2 == 0 {
			g[i] = base + 60
		}
	}
	return g
}

func TestSplitByTimeWindow(t *testing.T) {
	burstTestDefaults()
	base := time.Date(2026, 8, 1, 10, 0, 0, 0, time.UTC)

	// 0s, 2s, 4s 同组；10s 间隔超 5s 切分；再 1s 同组
	list := []burstPhotoInfo{
		mkBurstPhoto('A', base, nil),
		mkBurstPhoto('B', base.Add(2*time.Second), nil),
		mkBurstPhoto('C', base.Add(4*time.Second), nil),
		mkBurstPhoto('D', base.Add(14*time.Second), nil),
		mkBurstPhoto('E', base.Add(15*time.Second), nil),
	}

	groups := splitByTimeWindow(list, 5*time.Second)
	if len(groups) != 2 {
		t.Fatalf("groups = %d, want 2", len(groups))
	}
	if len(groups[0]) != 3 || len(groups[1]) != 2 {
		t.Errorf("group sizes = [%d, %d], want [3, 2]", len(groups[0]), len(groups[1]))
	}
}

func TestSplitBySimilarity_HashSplit(t *testing.T) {
	burstTestDefaults()
	base := time.Date(2026, 8, 1, 10, 0, 0, 0, time.UTC)

	// A/B 相同图（距离 0），B/C 距离超灰区上界（构图完全不同），C/D 相同
	list := []burstPhotoInfo{
		mkBurstPhoto('A', base, flatGray(100)),
		mkBurstPhoto('B', base.Add(2*time.Second), flatGray(100)),
		mkBurstPhoto('C', base.Add(4*time.Second), grayWithBits(100, 40)),
		mkBurstPhoto('D', base.Add(5*time.Second), grayWithBits(100, 40)),
	}

	groups := splitBySimilarity(list)
	if len(groups) != 2 {
		t.Fatalf("groups = %d, want 2", len(groups))
	}
	if len(groups[0]) != 2 || len(groups[1]) != 2 {
		t.Errorf("group sizes = [%d, %d], want [2, 2]", len(groups[0]), len(groups[1]))
	}
	// hashDist 记录在组内成员上
	if list[1].hashDist != 0 {
		t.Errorf("B hashDist = %d, want 0", list[1].hashDist)
	}
}

// grayWithRowMarks 在均匀底色上，把前 rows 行的 4 个奇数位像素（x=1/3/5/7）抬高。
// 全均匀图 dHash 全 0，每个孤立高像素恰贡献 1 个梯度位 → 汉明距离 = rows*4。
func grayWithRowMarks(base, mark float64, rows int) []float64 {
	g := flatGray(base)
	for y := 0; y < rows && y < burstGrayH; y++ {
		for _, x := range []int{1, 3, 5, 7} {
			g[y*burstGrayW+x] = mark
		}
	}
	return g
}

func TestSplitBySimilarity_GrayZoneSSIM(t *testing.T) {
	burstTestDefaults()
	base := time.Date(2026, 8, 1, 10, 0, 0, 0, time.UTC)

	// 灰区构造：3 行标记 → 距离 12（灰区上界内）。
	// 同样的标记位置，mark 与底色差小 → SSIM 高（灰区过，同组）；
	// 差大 → SSIM 低（灰区不过，切分）。
	gFlat := flatGray(100)
	gMarkSmall := grayWithRowMarks(100, 105, 3) // SSIM ≈ 0.94 ≥ 0.85
	gMarkLarge := grayWithRowMarks(100, 180, 3) // SSIM ≈ 0.06 < 0.85

	if d := hammingDist(dHashOf(gFlat), dHashOf(gMarkSmall)); d != 12 {
		t.Fatalf("setup: dist(small) = %d, want 12", d)
	}
	if d := hammingDist(dHashOf(gFlat), dHashOf(gMarkLarge)); d != 12 {
		t.Fatalf("setup: dist(large) = %d, want 12", d)
	}

	// 灰区 + SSIM 高 → 同组
	list := []burstPhotoInfo{
		mkBurstPhoto('A', base, gFlat),
		mkBurstPhoto('B', base.Add(2*time.Second), gMarkSmall),
	}
	if s := calcSSIM(gFlat, gMarkSmall); s < conf.C.Burst.SsimThreshold {
		t.Fatalf("setup: SSIM(small) = %f, want >= %f", s, conf.C.Burst.SsimThreshold)
	}
	if groups := splitBySimilarity(list); len(groups) != 1 {
		t.Fatalf("groups = %d, want 1 (gray zone SSIM pass)", len(groups))
	}

	// 灰区 + SSIM 低 → 切分
	list2 := []burstPhotoInfo{
		mkBurstPhoto('A', base, gFlat),
		mkBurstPhoto('B', base.Add(2*time.Second), gMarkLarge),
	}
	if s := calcSSIM(gFlat, gMarkLarge); s >= conf.C.Burst.SsimThreshold {
		t.Fatalf("setup: SSIM(large) = %f, want < %f", s, conf.C.Burst.SsimThreshold)
	}
	if groups := splitBySimilarity(list2); len(groups) != 2 {
		t.Fatalf("groups = %d, want 2 (gray zone SSIM fail)", len(groups))
	}
}

func TestSplitBurstGroups_SingleNotGroup(t *testing.T) {
	burstTestDefaults()
	base := time.Date(2026, 8, 1, 10, 0, 0, 0, time.UTC)

	// 时间窗内只有 1 张（前后间隔都超窗），算法产出的组仅 1 张，
	// 由 rebuildBurstGroups 过滤（len < 2 不建组）。此处验证分割行为本身。
	list := []burstPhotoInfo{
		mkBurstPhoto('A', base, flatGray(100)),
		mkBurstPhoto('B', base.Add(30*time.Second), flatGray(100)),
	}
	groups := splitBurstGroups(list)
	if len(groups) != 2 {
		t.Fatalf("groups = %d, want 2", len(groups))
	}
	for _, g := range groups {
		if len(g) != 1 {
			t.Errorf("group size = %d, want 1", len(g))
		}
	}
}

func TestCalcSSIM(t *testing.T) {
	// 完全相同 → 1
	if v := calcSSIM(flatGray(100), flatGray(100)); v < 0.999 {
		t.Errorf("SSIM(identical) = %f, want 1.0", v)
	}
	// 全黑 vs 全白（常数图分母退化）→ 视作不相似返回 1 的约定下，
	// 常数图 SSIM 分母含 C1/C2 常数项，值仍可计算且低于阈值
	v := calcSSIM(flatGray(0), flatGray(255))
	t.Logf("SSIM(black, white) = %f", v)
	if v > 0.85 {
		t.Errorf("SSIM(black, white) = %f, should be below threshold", v)
	}
	// 尺寸不符 → 0
	if v := calcSSIM(flatGray(100), []float64{1, 2, 3}); v != 0 {
		t.Errorf("SSIM(size mismatch) = %f, want 0", v)
	}
}

func TestHammingDist(t *testing.T) {
	if d := hammingDist(0, 0); d != 0 {
		t.Errorf("dist(0,0) = %d, want 0", d)
	}
	if d := hammingDist(0, 0xFF); d != 8 {
		t.Errorf("dist(0,0xFF) = %d, want 8", d)
	}
	if d := hammingDist(0x0F0F0F0F0F0F0F0F, 0xF0F0F0F0F0F0F0F0); d != 64 {
		t.Errorf("dist(complement) = %d, want 64", d)
	}
}

func TestParseGrayTxt(t *testing.T) {
	// 模拟 convert txt: 输出（首行注释 + 部分像素行）
	out := `# ImageMagick pixel enumeration: 9,8,255,gray
0,0: (183.4,183.4,183.4)  #B7B7B7  gray(71.9%)
1,0: (209.6,209.6,209.6)  #D2D2D2  gray(82.2%)
`
	if _, err := parseGrayTxt([]byte(out)); err == nil {
		t.Error("expected error for incomplete pixels, got nil")
	}

	// 完整 72 像素：值按行优先递增（行 y 列 x 的值 = y*9+x）
	full := "# ImageMagick pixel enumeration: 9,8,255,gray\n"
	for y := 0; y < burstGrayH; y++ {
		for x := 0; x < burstGrayW; x++ {
			full += line(x, y, float64(y*burstGrayW+x))
		}
	}
	gray, err := parseGrayTxt([]byte(full))
	if err != nil {
		t.Fatalf("parseGrayTxt failed: %v", err)
	}
	if len(gray) != 72 {
		t.Fatalf("len = %d, want 72", len(gray))
	}
	// 行优先校验：最后一个像素（x=8,y=7）= 7*9+8 = 71
	if gray[71] != 71 {
		t.Errorf("gray[71] = %f, want 71", gray[71])
	}
	// 第 3 行第 2 列（x=2,y=3）= 3*9+2 = 29
	if gray[3*burstGrayW+2] != 29 {
		t.Errorf("gray[row3 col2] = %f, want 29", gray[3*burstGrayW+2])
	}
}

func line(x, y int, v float64) string {
	return strconv.Itoa(x) + "," + strconv.Itoa(y) + ": (" +
		strconv.FormatFloat(v, 'f', -1, 64) + "," +
		strconv.FormatFloat(v, 'f', -1, 64) + "," +
		strconv.FormatFloat(v, 'f', -1, 64) + ")  #AAAAAA  gray(50%)\n"
}
