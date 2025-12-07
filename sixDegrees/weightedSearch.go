package sixdegrees

import (
	"math"

	utils "github.com/Jonnymurillo288/GoUtils"
)

// ============================ Strategies & Context ============================

type WeightStrategy interface {
	Weight(target, from, to *Artists, ctx EdgeContext) float64
}

type EdgeContext struct {
	SharedCount   int     // number of shared tracks connecting from->to
	IsCompilation bool    // whether connection derives from a compilation only
	RecencyScore  float64 // 0..1 where 1 is most recent
}

type PopularityDiffStrategy struct{}

func (PopularityDiffStrategy) Weight(target, from, to *Artists, _ EdgeContext) float64 {
	return math.Abs(target.Popularity - to.Popularity)
}

type CollabStrengthStrategy struct{}

func (CollabStrengthStrategy) Weight(_ *Artists, _ *Artists, _ *Artists, ctx EdgeContext) float64 {
	if ctx.SharedCount <= 0 {
		return 10.0
	}
	return 1.0 / float64(ctx.SharedCount)
}

// ============================== Graph & Edges ================================

type EdgeKey struct{ From, To string }

type Graph struct {
	Keys map[string]int // artist name -> vertex index
	Adj  map[int][]Edge // adjacency list by vertex index
}

func NewGraph() *Graph {
	return &Graph{
		Adj:  make(map[int][]Edge),
		Keys: make(map[string]int),
	}
}

type Edge struct {
	V, W   *Artists
	Weight float64
}

func NewEdge(target, from, to *Artists) Edge {
	return Edge{
		V:      from,
		W:      to,
		Weight: math.Abs(target.Popularity - to.Popularity),
	}
}

func (e Edge) To() string {
	if e.V == nil || e.W == nil {
		return "Error"
	}
	return e.W.Name
}

func (e Edge) From() string {
	if e.V == nil || e.W == nil {
		return "Error"
	}
	return e.V.Name
}

func (g *Graph) AddEdge(e Edge) {
	// ensure key for From
	fromName := e.From()
	if fromName == "Error" {
		return
	}
	fromIdx, ok := g.Keys[fromName]
	if !ok {
		fromIdx = len(g.Keys)
		g.Keys[fromName] = fromIdx
	}
	// ensure key for To
	toName := e.To()
	if toName != "Error" {
		if _, ok := g.Keys[toName]; !ok {
			g.Keys[toName] = len(g.Keys)
		}
	}
	// append edge
	g.Adj[fromIdx] = append(g.Adj[fromIdx], e)
}

// ================================ Dijkstra ===================================

type Dijkstra struct {
	DistTo   []float64
	EdgeTo   []Edge
	PQ       utils.IndexMinPQ
	Strategy WeightStrategy
	Meta     map[EdgeKey]EdgeContext
	Target   *Artists
}

func NewDijkstras(g *Graph, s *Artists) Dijkstra {
	return NewDijkstrasWithStrategy(g, s, nil, nil)
}

func NewDijkstrasWithStrategy(g *Graph, s *Artists, strat WeightStrategy, meta map[EdgeKey]EdgeContext) Dijkstra {
	// determine capacity from max key
	maxKey := -1
	for _, idx := range g.Keys {
		if idx > maxKey {
			maxKey = idx
		}
	}
	n := maxKey + 2 // breathing room for PQ implementations using 1-based indexing
	if n < 2 {
		n = 2
	}

	d := Dijkstra{
		EdgeTo:   make([]Edge, n),
		DistTo:   make([]float64, n),
		PQ:       utils.NewIndexMinPQ(n),
		Strategy: strat,
		Meta:     meta,
		Target:   s,
	}
	for i := range d.DistTo {
		d.DistTo[i] = math.Inf(1)
	}

	// ensure start vertex exists
	startIdx, ok := g.Keys[s.Name]
	if !ok {
		startIdx = len(g.Keys)
		g.Keys[s.Name] = startIdx
		// ensure an empty adjacency list to avoid nil map lookups later
		if _, exists := g.Adj[startIdx]; !exists {
			g.Adj[startIdx] = nil
		}
	}

	d.DistTo[startIdx] = 0.0
	d.PQ.Insert(startIdx, 0.0)

	for !d.PQ.IsEmpty() {
		v := d.PQ.DelMin()
		for _, e := range g.Adj[v] {
			d.relax(e, g.Keys)
		}
	}
	return d
}

func (d *Dijkstra) relax(e Edge, keys map[string]int) {
	fromName := e.From()
	toName := e.To()
	if fromName == "Error" || toName == "Error" {
		return
	}

	v, vok := keys[fromName]
	w, wok := keys[toName]
	if !vok || !wok || v == w {
		// unknown vertex or self-loop; ignore
		return
	}

	// choose weight
	edgeWeight := e.Weight
	if d.Strategy != nil {
		ctx := EdgeContext{}
		if d.Meta != nil {
			if c, ok := d.Meta[EdgeKey{From: fromName, To: toName}]; ok {
				ctx = c
			}
		}
		edgeWeight = d.Strategy.Weight(d.Target, e.V, e.W, ctx)
	}
	if math.IsNaN(edgeWeight) || math.IsInf(edgeWeight, 0) {
		return
	}

	newDist := d.DistTo[v] + edgeWeight
	if newDist < d.DistTo[w] {
		d.DistTo[w] = newDist
		d.EdgeTo[w] = e
		if d.PQ.Contains(w) {
			// best-effort: decrease the key; if your PQ returns an error, ignore
			d.PQ.DecreaseKey(w, newDist)
		} else {
			d.PQ.Insert(w, newDist)
		}
	}
}
