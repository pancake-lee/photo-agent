package data

import (
	"errors"
	"fmt"
	"time"

	"backend/internal/pkg/db"

	"github.com/pancake-lee/pgo/pkg/papp"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

// GetAppSetting 读取指定 key 的配置值，key 不存在时返回空串。
func (*appSettingDAO) GetAppSetting(ctx *papp.AppCtx, key string) (string, error) {
	q := db.GetQuery().AppSetting
	setting, err := q.WithContext(ctx).
		Where(q.Key.Eq(key)).
		First()
	if err != nil {
		// 查无记录视为"未配置"
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return "", nil
		}
		return "", fmt.Errorf("get app_setting %s failed: %w", key, err)
	}
	return setting.Value, nil
}

// SetAppSetting 写入配置值（key 已存在则覆盖）。
func (*appSettingDAO) SetAppSetting(ctx *papp.AppCtx, key, value string) error {
	q := db.GetQuery().AppSetting
	do := &AppSettingDO{
		Key:       key,
		Value:     value,
		UpdatedAt: time.Now(),
	}
	if err := q.WithContext(ctx).Clauses(clause.OnConflict{UpdateAll: true}).
		Create(do); err != nil {
		return fmt.Errorf("set app_setting %s failed: %w", key, err)
	}
	return nil
}
