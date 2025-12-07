//go:build integration
// +build integration

package sixdegrees

import (
	"testing"

	"github.com/Jonnymurillo288/SixDegreesSpotify/spotify"
)

func TestAppendArtistTracks(t *testing.T) {
	art := InputArtist("Eminem")
	albums,_ := spotify.ArtistAlbums(art.ID,1)
	h := NewHelper()
	for _,al := range art.ParseAlbums(albums) {
		tr, _ := spotify.GetAlbumTracks(al)
		T,_ := art.CreateTracks(tr,h)
		art.Tracks = append(art.Tracks,T...)
	}
}
