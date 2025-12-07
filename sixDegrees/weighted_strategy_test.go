package sixdegrees

import (
	"math"
	"testing"
)

func TestPopularityDiffStrategy(t *testing.T) {
	target := &Artists{Name: "T", Popularity: 80}
	from := &Artists{Name: "A", Popularity: 10}
	to := &Artists{Name: "B", Popularity: 65}
	w := PopularityDiffStrategy{}.Weight(target, from, to, EdgeContext{})
	if w != math.Abs(target.Popularity-to.Popularity) {
		t.Fatalf("unexpected weight: %v", w)
	}
}

func TestCollabStrengthStrategy(t *testing.T) {
	target := &Artists{Name: "T"}
	from := &Artists{Name: "A"}
	to := &Artists{Name: "B"}
	w0 := CollabStrengthStrategy{}.Weight(target, from, to, EdgeContext{SharedCount: 0})
	if w0 <= 1.0 {
		t.Fatalf("expected penalty for zero shared count, got %v", w0)
	}
	w := CollabStrengthStrategy{}.Weight(target, from, to, EdgeContext{SharedCount: 4})
	if w != 0.25 {
		t.Fatalf("expected 1/4 weight, got %v", w)
	}
}
