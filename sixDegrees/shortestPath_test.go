//go:build integration
// +build integration

package sixdegrees

import (
	"fmt"
	"log"
	"os"
	"testing"

	"github.com/Jonnymurillo288/SixDegreesSpotify/spotify"
)

// 1. Create starting artist
// 2. Using BFS search create edges for all artists connections
// 3. Create graph with the edges
// 4. Create shortest path object
// 5. Run PathTo(target)
func TestShortestPath(t *testing.T) {
	g := NewGraph()

	art := InputArtist("lil wayne")
	target := InputArtist("YG")
	albums,_ := spotify.ArtistAlbums(art.ID,10)
	h := NewHelper()
	for _,al := range art.ParseAlbums(albums) {
		tr,_  := spotify.GetAlbumTracks(al)
		T,_ := art.CreateTracks(tr,h)
		art.Tracks = append(art.Tracks,T...)
	}
	searchHelp, ret := RunSearch(art,target)
	if !ret {
		log.Fatalf("Could not find (%v) target %v",target.Name,searchHelp.ArtistMap)
		os.Exit(1)
	}
	// for artistname, []*Artists
	for k,artists := range searchHelp.EdgeTo {
		// v = ArtistObject
		v := searchHelp.ArtistMap[k]
		// edgefrom v to w
		for _,w := range artists {
			g.AddEdge(NewEdge(target,v,w))
		}
	}

	dij := NewDijkstras(g,art)
	for _,e := range dij.EdgeTo {
		v := g.Keys[e.From()]
		w := g.Keys[e.To()]
		fmt.Printf("\nPath: %v --> %v : %v",v,w,dij.DistTo[w])
	}
}
