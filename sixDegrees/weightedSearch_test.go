package sixdegrees

import (
	"math"
	"testing"
)

// Behaviors covered:
// 1) Graph.AddEdge assigns keys for both vertices and appends to adjacency list
// 2) NewEdge computes absolute weight using target and 'to' popularity
// 3) Dijkstra computes distances across chained edges when no direct edge exists
// 4) Dijkstra ignores invalid edges (nil endpoints) without panicking
// 5) Dijkstra handles self-loops without infinite processing

func TestWeightedSearch_AddEdge_AssignsKeysForBothVertices(t *testing.T) {
	g := NewGraph()
	// setup artists
	target := &Artists{Name: "Target", Popularity: 50}
	from := &Artists{Name: "A", Popularity: 40}
	to := &Artists{Name: "B", Popularity: 60}

	e := NewEdge(target, from, to)
	g.AddEdge(e)

	if len(g.Keys) != 2 {
		t.Fatalf("expected 2 keys, got %d", len(g.Keys))
	}
	v, ok := g.Keys[from.Name]
	if !ok {
		t.Fatalf("missing key for from vertex %q", from.Name)
	}
	if _, ok := g.Keys[to.Name]; !ok {
		t.Fatalf("missing key for to vertex %q", to.Name)
	}
	if len(g.Adj[v]) != 1 {
		t.Fatalf("expected 1 edge in adjacency list for %q, got %d", from.Name, len(g.Adj[v]))
	}
}

func TestWeightedSearch_NewEdge_ComputesWeight(t *testing.T) {
	target := &Artists{Name: "Target", Popularity: 90}
	from := &Artists{Name: "From", Popularity: 10}
	to := &Artists{Name: "To", Popularity: 75}
	e := NewEdge(target, from, to)
	want := math.Abs(target.Popularity - to.Popularity)
	if e.Weight != want {
		t.Fatalf("expected weight %v, got %v", want, e.Weight)
	}
}

func TestWeightedSearch_Dijkstra_ChainPath(t *testing.T) {
	g := NewGraph()
	target := &Artists{Name: "Target", Popularity: 50}

	A := &Artists{Name: "A", Popularity: 10}
	B := &Artists{Name: "B", Popularity: 40}
	C := &Artists{Name: "C", Popularity: 49}

	// Only path available is A -> B -> C
	g.AddEdge(NewEdge(target, A, B))
	g.AddEdge(NewEdge(target, B, C))

	d := NewDijkstras(g, A)

	keyC := g.Keys[C.Name]
	keyB := g.Keys[B.Name]
	if math.IsInf(d.DistTo[keyC], 1) {
		t.Fatalf("distance to C should be finite")
	}
	want := math.Abs(target.Popularity-B.Popularity) + math.Abs(target.Popularity-C.Popularity)
	if d.DistTo[keyC] != want {
		t.Fatalf("expected distance %v to C, got %v", want, d.DistTo[keyC])
	}
	// EdgeTo for C should be from B -> C
	e := d.EdgeTo[keyC]
	if e.From() != B.Name || e.To() != C.Name {
		t.Fatalf("expected last edge B->C, got %s->%s", e.From(), e.To())
	}
	// Distance to B should equal |T - B|
	wantB := math.Abs(target.Popularity - B.Popularity)
	if d.DistTo[keyB] != wantB {
		t.Fatalf("expected distance %v to B, got %v", wantB, d.DistTo[keyB])
	}
}

func TestWeightedSearch_Dijkstra_IgnoresInvalidEdges(t *testing.T) {
	g := NewGraph()
	target := &Artists{Name: "Target", Popularity: 50}
	A := &Artists{Name: "A", Popularity: 10}
	B := &Artists{Name: "B", Popularity: 40}

	// Valid edge to ensure graph has at least one path and keys
	g.AddEdge(NewEdge(target, A, B))
	// Append an invalid edge A -> nil directly (bypass AddEdge which validates keys)
	keyA := g.Keys[A.Name]
	g.Adj[keyA] = append(g.Adj[keyA], Edge{V: A, W: nil, Weight: 0})

	// No panic should occur; algorithm should ignore invalid edge
	_ = NewDijkstras(g, A)
}

func TestWeightedSearch_Dijkstra_SelfLoopTerminates(t *testing.T) {
	g := NewGraph()
	A := &Artists{Name: "A", Popularity: 10}

	// self-loop on A
	g.AddEdge(Edge{V: A, W: A, Weight: 5})

	d := NewDijkstras(g, A)
	keyA := g.Keys[A.Name]
	if d.DistTo[keyA] != 0 {
		t.Fatalf("expected distance to start to remain 0, got %v", d.DistTo[keyA])
	}
}