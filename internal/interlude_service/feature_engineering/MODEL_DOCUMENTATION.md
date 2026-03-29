# Model Documentation: Logit Model Version Validation Metrics

## 1. Model Overview
Logistic Regression for Predicting Neighbors based on Embeddings Space of Two artists

### 1.1 Model Name
logit_model_v1.joblib

### 1.2 Model Type
Logistic Regression

### 1.3 Purpose
Predicting Neighbors based on Embeddings Space of Two artists

### 1.4 Owner / Maintainer
<!-- Team or individual responsible -->

### 1.5 Last Updated
1/27/2026

### 1.6 IMPORTANT NOTES!!
- Currently the model is heavily favored to who is popular.
- Ex: Frank Sinatra - With current popular artists (Dua Lip, Kendrick Lamar, etc)
Potential Solutions:
- During training:
  - Add a time filter
  - Add artist tracks, genres, etc
- During Inference
  - Increase our samples for building predictions 
---

## 2. Data

### 2.1 Training Data
| Attribute | Value |
|-----------|-------|
| Source | |
| Date Range | |
| Sample Size | |
| Features Count | |

### 2.2 Feature Definitions
| Feature Name | Type | Description | Source |
|--------------|------|-------------|--------|
| | | | |
| | | | |
| | | | |

### 2.3 Target Variable
Artist Collaboration = 1 | 0

### 2.4 Data Preprocessing
<!-- Transformations, encoding, scaling, handling missing values -->

---

## 3. Model Architecture

### 3.1 Algorithm
<!-- Detailed algorithm description -->

### 3.2 Hyperparameters
| Parameter | Value | Description |
|-----------|-------|-------------|
| | | |
| | | |

### 3.3 Feature Engineering
<!-- Feature transformations, interactions, derived features -->

### 3.4 Regularization
<!-- L1/L2 penalties, dropout, etc. -->

---

## 4. Training

### 4.1 Training Configuration
| Setting | Value |
|---------|-------|
| Train/Val/Test Split | |
| Cross-Validation | |
| Random Seed | |
| Training Duration | |

### 4.2 Optimization
<!-- Optimizer, learning rate, convergence criteria -->

### 4.3 Hardware / Environment
<!-- Training infrastructure details -->

---

## 5. Validation Metrics

### 5.1 Classification Metrics
Label distribution:
label
1    1107234
0     221446
Name: count, dtype: int64
Training set: 1062944 samples
  Positive: 885787
  Negative: 177157
Test set: 265736 samples
  Positive: 221447
  Negative: 44289

Training LogisticRegressionCV model...

Best C: 0.1000
Best l1_ratio: 0.8000

Training set performance:
  ROC AUC: 0.9168
  PR AUC: 0.9032
  Log Loss: 0.4175
  Brier Score: 0.1210
  Accuracy: 0.8364
  Precision: 0.8048
  Recall: 0.8883
  F1 Score: 0.8445

Test set performance:
  ROC AUC: 0.9165
  PR AUC: 0.9028
  Log Loss: 0.4185
  Brier Score: 0.1214
  Accuracy: 0.8357
  Precision: 0.8039
  Recall: 0.8880
  F1 Score: 0.8439

Classification Report (Test Set):
              precision    recall  f1-score   support

     No Link       0.87      0.78      0.83    200000
        Link       0.80      0.89      0.84    200000

    accuracy                           0.84    400000
   macro avg       0.84      0.84      0.84    400000
weighted avg       0.84      0.84      0.84    400000


## 6. Model Coefficients

### 6.1 Feature Importance
Features by absolute coefficient:
                                 feature      coef  abs_coef
11                     jaccard_neighbors  2.327233  2.327233
3               mean_topk_cos_dstnbr_src  1.646560  1.646560
14                       l2_dist_src_dst -1.061643  1.061643
2                     max_cos_srcnbr_dst  0.994665  0.994665
4                preferential_attachment  0.986655  0.986655
15                     num_dst_neighbors  0.642545  0.642545
8                            adamic_adar  0.581450  0.581450
1                        cos_sim_src_dst -0.486250  0.486250
7                            dot_src_dst -0.486250  0.486250
13                        popularity_dst  0.248459  0.248459
16                        popularity_src  0.169645  0.169645
5   similarity_prop_genre_rosamerica_rhy -0.062533  0.062533
10  similarity_prop_genre_rosamerica_pop -0.052498  0.052498
17  similarity_prop_genre_rosamerica_jaz -0.050388  0.050388
0   similarity_prop_genre_rosamerica_spe -0.042814  0.042814
12  similarity_prop_genre_rosamerica_roc -0.027878  0.027878
9   similarity_prop_genre_rosamerica_hip -0.026797  0.026797
6   similarity_prop_genre_rosamerica_dan -0.021325  0.021325

---

## 7. Version History

| Version | Date | Changes | Metrics Delta |
|---------|------|---------|---------------|
| v1    | 1/27/26 |        |               |
| v2    | 2/4/2026| added genre information | Ever so slightly better precision/recall |
| v3    | 2/5/26  | embeddings 32 -> 64, walks 5 -> 10 | Better recall, better precision. especially on the no links
| v4    | 2/5/26  | embeddings -> 128, walks -> 20 | Same increase, marginally better
| v5    | 2/11/26 | Positive-Unlabled Weight | Better no link recall and precision, worse on links
---

## 8. Deployment

### 8.1 Serving Infrastructure
<!-- Where and how the model is deployed -->

### 8.2 Input Schema
```json
{
  "feature_1": "type",
  "feature_2": "type"
}
```

### 8.3 Output Schema
```json
{
  "prediction": "type",
  "probability": "type"
}
```

### 8.4 Latency Requirements
10 Minutes based on the previous 1.4 million rows

---

## 9. Monitoring

### 9.1 Performance Monitoring
<!-- Metrics tracked in production -->
None at the time. 

### 9.2 Data Drift Detection
<!-- How input distribution shifts are monitored -->

### 9.3 Alerting Thresholds
| Metric | Warning | Critical |
|--------|---------|----------|
| | | |

---

## 10. Limitations & Known Issues

### 10.1 Model Limitations
<!-- Known weaknesses, edge cases -->
Model does not account for age, or time period of the two artists

### 10.2 Bias Considerations
<!-- Fairness analysis, protected attributes -->

### 10.3 Out-of-Scope Use Cases
<!-- Where this model should NOT be used -->

---

## 11. References

### 11.1 Related Documentation
<!-- Links to related docs, notebooks, papers -->

### 11.2 Code Repository
<!-- Link to model training code -->

### 11.3 Data Lineage
<!-- Link to data pipeline documentation -->

---

## 12. Approval & Sign-off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Data Scientist | | | |
| ML Engineer | | | |
| Product Owner | | | |
