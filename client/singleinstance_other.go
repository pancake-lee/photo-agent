//go:build !windows

package main

// ensureSingleInstance 非 Windows 平台无单实例约束（开发态允许并行运行调试实例）。
func ensureSingleInstance() {}
