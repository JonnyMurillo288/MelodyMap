package sixdegrees

import (
	"fmt"
	"log"
	"testing"

	"github.com/Jonnymurillo288/SixDegreesSpotify/spotify"
)

func TestTracks(t *testing.T) {
	a := CreateArtists("Eminem","7dGJo4pcD2V6oG8kP0tJRR")
	lil := CreateArtists("lil wayne","55Aa2cqylxrFIXC767Z865")
	res := newTrack(a,"No Love","","7bHT9osSq1rwT2yaImzqCi",[]*Artists{lil})
	fmt.Println("Function newTrack():",res)
}

func TestAlbumGetsTracks(t *testing.T) {
	a := CreateArtists("Eminem","7dGJo4pcD2V6oG8kP0tJRR")
	albums,_ := spotify.ArtistAlbums(a.ID,1)
	h := NewHelper()
	tracks,_ := a.CreateTracks(albums,h)
	if len(tracks) < 50 {
		log.Fatalf("Were only getting %v tracks from create tracks",len(tracks))
		log.Fatal(tracks[0],tracks[len(tracks)-4])
		fmt.Print("\n=================================\n")
	}
}

func TestAlbumGetsFeatured(t *testing.T) {
	a := CreateArtists("Eminem","7dGJo4pcD2V6oG8kP0tJRR")
	albums,_ := spotify.ArtistAlbums(a.ID,1)
	res := a.ParseAlbums(albums)
	if len(res) < 2 {
		log.Fatalf("Problem with getting artists from Album %v",res)
		fmt.Print("\n==================================\n")
	}
}


