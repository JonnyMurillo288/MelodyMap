package machinelearning

import (
	"fmt"

	"github.com/Jonnymurillo288/MelodyMap/internal/search"
)

func main_run(req searchRequest, s *search.Store) (SearchResponse, error) {
	hops, stepsList, msg, status, err := search.SearchArtists(
		s,
		req.Start,
		req.Target,
		req.Depth,
		3000,
		false,
	)
	if err != nil {
		fmt.Println("Error searching artist:", err)
		return SearchResponse{}, err
	}

	// stepsList IS ALREADY []Step
	resp := SearchResponse{
		Start:    req.Start,
		Target:   req.Target,
		StartID:  req.StartID,
		TargetID: req.TargetID,
		Hops:     hops,
		Path:     stepsList,
		Message:  msg,
		Status:   status,
	}
	return resp, nil
}
