// Package service 提供照片处理相关领域工具函数（EXIF、时间线、描述文件、文件操作等）。
package service

import (
	"fmt"
	"image"
	_ "image/jpeg"
	_ "image/png"
	"os"
	"strings"
	"time"

	"github.com/pancake-lee/pgo/pkg/plogger"
	"github.com/rwcarlsen/goexif/exif"
)

// exifInfo EXIF 信息结构
type exifInfo struct {
	ShotAt       *time.Time
	Brand        string
	Model        string
	Lens         string
	FocalLength  string
	Aperture     string
	ISO          int
	ExposureTime string
	Latitude     *float64
	Longitude    *float64
	Altitude     *float64
}

// getExifInfo 从图片文件中读取完整 EXIF 信息
func getExifInfo(path string) *exifInfo {
	f, err := os.Open(path)
	if err != nil {
		plogger.Warnf("Open file for EXIF failed: %s %v", path, err)
		return nil
	}
	defer f.Close()

	x, err := exif.Decode(f)
	if err != nil {
		// 没有 EXIF 数据是正常情况
		return nil
	}

	info := &exifInfo{}

	// 拍摄时间
	if t, err := x.DateTime(); err == nil {
		info.ShotAt = &t
	}

	// 品牌
	if tag, err := x.Get(exif.Make); err == nil {
		info.Brand = normalizeBrand(strings.TrimSpace(tag.String()))
	}

	// 型号
	if tag, err := x.Get(exif.Model); err == nil {
		info.Model = strings.TrimRight(strings.TrimSpace(tag.String()), "\x00")
	}

	// 镜头
	if tag, err := x.Get(exif.LensModel); err == nil {
		info.Lens = strings.TrimRight(strings.TrimSpace(tag.String()), "\x00")
	}

	// 焦距
	if tag, err := x.Get(exif.FocalLength); err == nil {
		num, den, _ := tag.Rat2(0)
		if den != 0 {
			info.FocalLength = fmt.Sprintf("%.0fmm", float64(num)/float64(den))
		}
	}

	// 光圈
	if tag, err := x.Get(exif.FNumber); err == nil {
		num, den, _ := tag.Rat2(0)
		if den != 0 {
			info.Aperture = fmt.Sprintf("f/%.1f", float64(num)/float64(den))
		}
	}

	// ISO
	if tag, err := x.Get(exif.ISOSpeedRatings); err == nil {
		info.ISO, _ = tag.Int(0)
	}

	// 曝光时间
	if tag, err := x.Get(exif.ExposureTime); err == nil {
		num, den, _ := tag.Rat2(0)
		if den == 0 {
			info.ExposureTime = fmt.Sprintf("%.1f", float64(num))
		} else if num < den {
			info.ExposureTime = fmt.Sprintf("1/%d", den/num)
		} else {
			info.ExposureTime = fmt.Sprintf("%.1f", float64(num)/float64(den))
		}
	}

	// GPS
	if lat, lon, err := x.LatLong(); err == nil {
		info.Latitude = &lat
		info.Longitude = &lon
	}

	// 海拔
	if tag, err := x.Get(exif.GPSAltitude); err == nil {
		num, den, _ := tag.Rat2(0)
		if den != 0 {
			alt := float64(num) / float64(den)
			info.Altitude = &alt
		}
	}

	return info
}

// getExifShotAt 从图片文件中读取拍摄时间（快捷方法）
func getExifShotAt(path string) *time.Time {
	info := getExifInfo(path)
	if info == nil {
		return nil
	}
	return info.ShotAt
}

// getImageSize 获取图片尺寸
func getImageSize(path string) (int, int) {
	f, err := os.Open(path)
	if err != nil {
		return 0, 0
	}
	defer f.Close()

	cfg, _, err := image.DecodeConfig(f)
	if err != nil {
		return 0, 0
	}
	return cfg.Width, cfg.Height
}

// normalizeBrand 统一品牌名称
func normalizeBrand(make string) string {
	make = strings.ToUpper(strings.TrimSpace(make))
	known := map[string]string{
		"NIKON CORPORATION": "NIKON",
		"NIKON":             "NIKON",
		"CANON":             "CANON",
		"SONY":              "SONY",
		"FUJIFILM":          "FUJIFILM",
		"FUJI PHOTO FILM":   "FUJIFILM",
		"OLYMPUS":           "OLYMPUS",
		"PANASONIC":         "PANASONIC",
		"LEICA":             "LEICA",
		"RICOH":             "RICOH",
		"PENTAX":            "PENTAX",
		"SIGMA":             "SIGMA",
		"HASSELBLAD":        "HASSELBLAD",
		"PHASE ONE":         "PHASE ONE",
		"DJI":               "DJI",
		"APPLE":             "APPLE",
		"SAMSUNG":           "SAMSUNG",
		"GOOGLE":            "GOOGLE",
		"HUAWEI":            "HUAWEI",
		"XIAOMI":            "XIAOMI",
	}
	for prefix, brand := range known {
		if strings.HasPrefix(make, prefix) {
			return brand
		}
	}
	return make
}
