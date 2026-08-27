package service

import (
	"image"
	"image/color"
	"image/jpeg"
	"os"
	"path/filepath"
	"testing"
)

func writeTestJPEG(t *testing.T, path string) {
	t.Helper()
	file, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()

	img := image.NewRGBA(image.Rect(0, 0, 8, 6))
	for y := 0; y < 6; y++ {
		for x := 0; x < 8; x++ {
			img.Set(x, y, color.RGBA{R: uint8(x * 20), G: uint8(y * 20), B: 40, A: 255})
		}
	}
	if err := jpeg.Encode(file, img, nil); err != nil {
		t.Fatal(err)
	}
}

func TestValidateVlmInput(t *testing.T) {
	dir := t.TempDir()
	valid := filepath.Join(dir, "same.jpg")
	writeTestJPEG(t, valid)

	if err := validateVlmInput(valid); err != nil {
		t.Fatalf("valid JPG rejected: %v", err)
	}

	nef := filepath.Join(dir, "same.nef")
	if err := os.WriteFile(nef, []byte("not a JPG"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := validateVlmInput(nef); err == nil {
		t.Fatal("NEF accepted as VLM input")
	}

	broken := filepath.Join(dir, "broken.jpg")
	if err := os.WriteFile(broken, []byte("corrupt"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := validateVlmInput(broken); err == nil {
		t.Fatal("corrupt JPG accepted as VLM input")
	}
}

func TestResolveCompressOutputDoesNotReuseSameBasename(t *testing.T) {
	first, firstCleanup, err := resolveCompressOutput(filepath.Join("one", "same.jpg"))
	if err != nil {
		t.Fatal(err)
	}
	defer firstCleanup()
	second, secondCleanup, err := resolveCompressOutput(filepath.Join("two", "same.jpg"))
	if err != nil {
		t.Fatal(err)
	}
	defer secondCleanup()

	if first == second {
		t.Fatalf("same temporary output reused: %q", first)
	}
}
