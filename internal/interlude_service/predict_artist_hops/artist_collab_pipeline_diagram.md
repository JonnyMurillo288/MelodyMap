# Artist Collaboration → Track Generation (Simplified Diagram)

Below is a **high-level system diagram** suitable for a portfolio site.  
It emphasizes **data modeling**, **feature engineering**, **regression**, and **CVAE-based generation** without overwhelming detail.

---

## System Flow Diagram (Mermaid)

```mermaid
flowchart LR
    A[Music Databases<br/>(MusicBrainz, Spotify, AcousticBrainz)] --> B[Raw Tables]
    
    B --> C[Artist Collaboration Graph]
    B --> D[Track-Level Audio Features]
    
    C --> E[Artist Embeddings<br/>(Node2Vec)]
    
    E --> F[Artist Pair Features]
    C --> F
    D --> G[Aggregated Track Features]
    
    F --> H[Link Prediction Model<br/>(Logistic / Elastic Net)]
    
    H --> I[Collaboration Probability]
    
    F --> J[CVAE Conditioning Vector X]
    I --> J
    
    G --> K[Target Track Features Y]
    
    J --> L[Conditional VAE]
    K --> L
    
    L --> M[Synthetic Track Feature Generation]
```

---

## How to Read This Diagram

### 1. Data Ingestion
Multiple music data sources are normalized into structured tables:
- Artist relationships
- Track metadata
- Audio features

### 2. Graph & Embeddings
- Artists form a collaboration graph
- Node2Vec embeddings encode creative proximity

### 3. Feature Engineering
Artist-pair features combine:
- Embedding similarity
- Graph reachability
- Popularity context

### 4. Regression Layer
A supervised **link prediction model** estimates:
> *How likely are two artists to collaborate?*

This probability becomes an explicit conditioning signal.

### 5. Generative Layer (CVAE)
The CVAE learns:
- Latent structure of real collaborations
- Multimodal distributions of track features

It generates **plausible, controllable synthetic tracks** conditioned on artist pairs.

---

## Why This Architecture Works (Portfolio Framing)

- **Separation of concerns**
  - Regression = feasibility
  - CVAE = creativity

- **Interpretable + generative**
  - Probabilities are inspectable
  - Outputs are diverse, not deterministic

- **Scalable design**
  - Swap models without changing data contracts
  - Extend to genres, popularity targets, or constraints

---

*This diagram is intentionally simplified for communication clarity while reflecting a production-grade ML pipeline.*
