package service

import "testing"

func TestUniqueZipEntryNames(t *testing.T) {
	sources := []downloadPhotoSource{
		{name: "day/photo.jpg"},
		{name: "other/photo.jpg"},
		{name: "photo (2).jpg"},
		{name: "photo.jpg"},
		{name: "photo.nef"},
	}
	want := []string{"photo.jpg", "photo (2).jpg", "photo (2) (2).jpg", "photo (3).jpg", "photo.nef"}
	got := uniqueZipEntryNames(sources)
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("entry %d = %q, want %q", i, got[i], want[i])
		}
	}
}
