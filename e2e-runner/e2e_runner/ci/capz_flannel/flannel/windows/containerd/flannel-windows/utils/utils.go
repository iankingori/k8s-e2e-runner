package utils

import (
	"fmt"
	"os"
	"path/filepath"
)

func CopyFile(src, dest string) error {
	srcStat, err := os.Stat(src)
	if err != nil {
		return err
	}
	fmt.Printf("copy file %s to %s\n", src, dest)
	bytesRead, err := os.ReadFile(src)
	if err != nil {
		return err
	}
	if err = os.WriteFile(dest, bytesRead, srcStat.Mode()); err != nil {
		return err
	}
	return nil
}

func CopyFiles(srcDir, destDir string) error {
	files, err := os.ReadDir(srcDir)
	if err != nil {
		return err
	}
	for _, file := range files {
		if file.IsDir() {
			continue
		}
		src := filepath.Join(srcDir, file.Name())
		dest := filepath.Join(destDir, file.Name())
		if err := CopyFile(src, dest); err != nil {
			return err
		}
	}
	return nil
}
