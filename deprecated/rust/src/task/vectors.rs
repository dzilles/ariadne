use super::{
    sqlite::Connection,
    store::{limit, matches_filters, nonempty},
    *,
};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashMap};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EmbeddingModel {
    pub id: String,
    pub dimensions: usize,
}

/// Implement this with a real local or remote text-embedding model.
/// The ID must identify model weights, preprocessing, and vector-space version.
pub trait Embedder {
    fn model(&self) -> EmbeddingModel;
    fn embed(&self, text: &str) -> Result<Vec<f32>>;
}

/// A deterministic token-hashing fixture for offline demos, NOT a learned
/// semantic model. It measures token overlap and may have hash collisions.
pub struct DemoEmbedder;
impl Embedder for DemoEmbedder {
    fn model(&self) -> EmbeddingModel {
        EmbeddingModel {
            id: "demo-token-hash-v1".into(),
            dimensions: 128,
        }
    }
    fn embed(&self, text: &str) -> Result<Vec<f32>> {
        let mut vector = vec![0.0; self.model().dimensions];
        for token in text
            .to_lowercase()
            .split(|c: char| !c.is_alphanumeric())
            .filter(|s| !s.is_empty())
        {
            let hash = token
                .as_bytes()
                .iter()
                .fold(0xcbf29ce484222325_u64, |hash, byte| {
                    (hash ^ u64::from(*byte)).wrapping_mul(0x100000001b3)
                });
            vector[hash as usize % 128] += 1.0;
        }
        validate_vector(&vector, self.model().dimensions)?;
        Ok(vector)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EmbeddingJob {
    pub task_id: String,
    pub source: String,
    pub source_revision: u64,
    pub content: String,
    pub model: EmbeddingModel,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EmbeddingOutcome {
    Applied,
    Obsolete,
    AlreadyApplied,
}

#[derive(Debug, Clone, Serialize)]
pub struct IndexProgress {
    pub applied: usize,
    pub obsolete: usize,
    pub already_applied: usize,
}

#[derive(Debug, Clone, Serialize)]
pub struct IndexStatus {
    pub sources: usize,
    pub ready: usize,
    pub pending: usize,
    pub complete: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct SemanticHit {
    pub task: TaskSummary,
    pub score: f64,
    pub source: String,
}
#[derive(Debug, Clone, Serialize)]
pub struct SemanticResults {
    pub hits: Vec<SemanticHit>,
    pub index: IndexStatus,
    pub model: EmbeddingModel,
}

pub(crate) fn sync_sources(db: &Connection, task: &Task) -> Result<()> {
    let mut desired = BTreeMap::new();
    desired.insert("description".to_string(), task.description.clone());
    if !task.acceptance_criteria.is_empty() {
        desired.insert(
            "acceptance_criteria".to_string(),
            task.acceptance_criteria.join("\n"),
        );
    }
    if let Some(summary) = task
        .result_summary
        .as_ref()
        .filter(|s| !s.trim().is_empty())
    {
        desired.insert("result_summary".to_string(), summary.clone());
    }
    let existing = db.query(
        "SELECT source,content FROM task_sources WHERE task_id=?1",
        &[&task.id],
    )?;
    for row in &existing {
        if !desired.contains_key(&row[0]) {
            // FK cascades remove both pending jobs and any old vectors.
            db.run(
                "DELETE FROM task_sources WHERE task_id=?1 AND source=?2",
                &[&task.id, &row[0]],
            )?;
        }
    }
    for (source, content) in desired {
        if existing
            .iter()
            .any(|row| row[0] == source && row[1] == content)
        {
            continue;
        }
        // Task versions increase even when a source is removed and later restored:
        // an old job cannot become valid again through an A -> B -> A edit.
        db.run("INSERT INTO task_sources(task_id,source,revision,content) VALUES(?1,?2,?3,?4)
                ON CONFLICT(task_id,source) DO UPDATE SET revision=excluded.revision,content=excluded.content",
            &[&task.id, &source, &task.version.to_string(), &content])?;
        db.run(
            "DELETE FROM embeddings WHERE task_id=?1 AND source=?2",
            &[&task.id, &source],
        )?;
        db.run("INSERT INTO embedding_jobs(task_id,source,model,source_revision)
                SELECT ?1,?2,id,?3 FROM embedding_models WHERE 1
                ON CONFLICT(task_id,source,model) DO UPDATE SET source_revision=excluded.source_revision",
            &[&task.id, &source, &task.version.to_string()])?;
    }
    Ok(())
}

impl TaskStore {
    pub fn register_embedding_model(&mut self, model: &EmbeddingModel) -> Result<()> {
        nonempty("embedding model ID", &model.id)?;
        if model.dimensions == 0 || model.dimensions > 8192 {
            return Err(Error::invalid(
                "Embedding dimension must be between 1 and 8192",
            ));
        }
        self.transaction(|db| {
            let existing = db.query("SELECT dimensions FROM embedding_models WHERE id=?1", &[&model.id])?;
            if let Some(row) = existing.first() {
                if row[0] != model.dimensions.to_string() { return Err(Error::conflict("Model ID already exists with different dimensions; use a new model/version ID")); }
            } else {
                db.run("INSERT INTO embedding_models(id,dimensions) VALUES(?1,?2)", &[&model.id, &model.dimensions.to_string()])?;
            }
            enqueue_missing(db, &model.id)
        })
    }

    pub fn pending_embeddings(&self, model: &str, count: usize) -> Result<Vec<EmbeddingJob>> {
        let dimensions = model_dimensions(&self.db, model)?;
        let rows = self.db.query(
            "SELECT j.task_id,j.source,j.source_revision,s.content
            FROM embedding_jobs j JOIN task_sources s ON s.task_id=j.task_id AND s.source=j.source
            WHERE j.model=?1 AND j.source_revision=s.revision ORDER BY j.task_id,j.source LIMIT ?2",
            &[model, &limit(count).to_string()],
        )?;
        rows.into_iter()
            .map(|row| {
                Ok(EmbeddingJob {
                    task_id: row[0].clone(),
                    source: row[1].clone(),
                    source_revision: row[2]
                        .parse()
                        .map_err(|_| Error::invalid("Invalid source revision"))?,
                    content: row[3].clone(),
                    model: EmbeddingModel {
                        id: model.into(),
                        dimensions,
                    },
                })
            })
            .collect()
    }

    /// Embedding computation happens before this short transaction. The source
    /// revision is checked again before publishing; late results are discarded.
    pub fn complete_embedding(
        &mut self,
        job: &EmbeddingJob,
        vector: &[f32],
    ) -> Result<EmbeddingOutcome> {
        validate_vector(vector, job.model.dimensions)?;
        self.transaction(|db| {
            if model_dimensions(db, &job.model.id)? != job.model.dimensions { return Err(Error::conflict("Embedding model dimension mismatch")); }
            let source = db.query("SELECT revision,content FROM task_sources WHERE task_id=?1 AND source=?2", &[&job.task_id, &job.source])?;
            let Some(source) = source.first() else { return Ok(EmbeddingOutcome::Obsolete); };
            if source[0] != job.source_revision.to_string() { return Ok(EmbeddingOutcome::Obsolete); }
            if source[1] != job.content { return Err(Error::conflict("Embedding job content does not match its source revision")); }
            let pending = db.query("SELECT source_revision FROM embedding_jobs WHERE task_id=?1 AND source=?2 AND model=?3", &[&job.task_id, &job.source, &job.model.id])?;
            if pending.is_empty() {
                let ready = db.query("SELECT 1 FROM embeddings WHERE task_id=?1 AND source=?2 AND model=?3 AND source_revision=?4",
                    &[&job.task_id, &job.source, &job.model.id, &job.source_revision.to_string()])?;
                return if ready.is_empty() { Ok(EmbeddingOutcome::Obsolete) } else { Ok(EmbeddingOutcome::AlreadyApplied) };
            }
            if pending[0][0] != job.source_revision.to_string() { return Ok(EmbeddingOutcome::Obsolete); }
            db.run("INSERT INTO embeddings(task_id,source,model,source_revision,vector) VALUES(?1,?2,?3,?4,?5)
                ON CONFLICT(task_id,source,model) DO UPDATE SET source_revision=excluded.source_revision,vector=excluded.vector",
                &[&job.task_id, &job.source, &job.model.id, &job.source_revision.to_string(), &serde_json::to_string(vector)?])?;
            // Publishing and acknowledging the job happen in the SAME transaction.
            db.run("DELETE FROM embedding_jobs WHERE task_id=?1 AND source=?2 AND model=?3 AND source_revision=?4",
                &[&job.task_id, &job.source, &job.model.id, &job.source_revision.to_string()])?;
            Ok(EmbeddingOutcome::Applied)
        })
    }

    pub fn index_pending(
        &mut self,
        embedder: &impl Embedder,
        count: usize,
    ) -> Result<IndexProgress> {
        let model = embedder.model();
        self.register_embedding_model(&model)?;
        let jobs = self.pending_embeddings(&model.id, count)?;
        let mut progress = IndexProgress {
            applied: 0,
            obsolete: 0,
            already_applied: 0,
        };
        for job in jobs {
            // Failure leaves this job durable and pending for the next attempt.
            let vector = embedder.embed(&job.content)?;
            match self.complete_embedding(&job, &vector)? {
                EmbeddingOutcome::Applied => progress.applied += 1,
                EmbeddingOutcome::Obsolete => progress.obsolete += 1,
                EmbeddingOutcome::AlreadyApplied => progress.already_applied += 1,
            }
        }
        Ok(progress)
    }

    pub fn index_status(&self, project_id: &str, model: &str) -> Result<IndexStatus> {
        model_dimensions(&self.db, model)?;
        index_status(&self.db, project_id, model)
    }

    /// Rebuilding derived data preserves tasks and history. Jobs are re-created
    /// atomically, including when the previous worker stopped part-way through.
    pub fn rebuild_embeddings(&mut self, model: &str) -> Result<()> {
        self.transaction(|db| {
            model_dimensions(db, model)?;
            db.run("DELETE FROM embeddings WHERE model=?1", &[model])?;
            enqueue_missing(db, model)
        })
    }

    /// Exact cosine scan for prototype-sized datasets; only current source
    /// revisions in the requested project and vector space can participate.
    pub fn semantic_search(
        &mut self,
        query: &SearchQuery,
        embedder: &impl Embedder,
    ) -> Result<SemanticResults> {
        let text = query
            .text
            .as_deref()
            .ok_or_else(|| Error::invalid("Vector search requires text"))?;
        nonempty("search text", text)?;
        let model = embedder.model();
        let vector = embedder.embed(text)?;
        validate_vector(&vector, model.dimensions)?;
        self.transaction(|db| {
            if model_dimensions(db, &model.id)? != model.dimensions { return Err(Error::conflict("Search provider differs from the registered model")); }
            let rows = db.query("SELECT t.data,s.source,e.vector FROM embeddings e
                JOIN task_sources s ON s.task_id=e.task_id AND s.source=e.source AND s.revision=e.source_revision
                JOIN tasks t ON t.id=s.task_id
                WHERE t.project_id=?1 AND e.model=?2", &[&query.project_id, &model.id])?;
            let mut best: HashMap<String, SemanticHit> = HashMap::new();
            for row in rows {
                let task: Task = serde_json::from_str(&row[0])?;
                if !matches_filters(&task, query) { continue; }
                let candidate: Vec<f32> = serde_json::from_str(&row[2])?;
                validate_vector(&candidate, model.dimensions)?;
                let score = cosine(&vector, &candidate);
                let hit = SemanticHit { task: TaskSummary::from(&task), score, source: row[1].clone() };
                if best.get(&task.id).is_none_or(|old| score > old.score) { best.insert(task.id, hit); }
            }
            let mut hits: Vec<_> = best.into_values().collect();
            hits.sort_by(|a, b| b.score.total_cmp(&a.score).then(a.task.id.cmp(&b.task.id)));
            hits.truncate(limit(query.limit));
            Ok(SemanticResults { hits, index: index_status(db, &query.project_id, &model.id)?, model: model.clone() })
        })
    }
}

fn enqueue_missing(db: &Connection, model: &str) -> Result<()> {
    db.run("INSERT INTO embedding_jobs(task_id,source,model,source_revision)
        SELECT s.task_id,s.source,?1,s.revision FROM task_sources s
        WHERE NOT EXISTS (SELECT 1 FROM embeddings e WHERE e.task_id=s.task_id AND e.source=s.source AND e.model=?1 AND e.source_revision=s.revision)
        ON CONFLICT(task_id,source,model) DO UPDATE SET source_revision=excluded.source_revision", &[model])
}

fn model_dimensions(db: &Connection, model: &str) -> Result<usize> {
    db.scalar(
        "SELECT dimensions FROM embedding_models WHERE id=?1",
        &[model],
    )?
    .parse()
    .map_err(|_| Error::invalid("Invalid embedding dimensions"))
}

fn index_status(db: &Connection, project: &str, model: &str) -> Result<IndexStatus> {
    let row = db.query("SELECT
        (SELECT count(*) FROM task_sources s JOIN tasks t ON t.id=s.task_id WHERE t.project_id=?1),
        (SELECT count(*) FROM embeddings e JOIN task_sources s ON s.task_id=e.task_id AND s.source=e.source AND s.revision=e.source_revision JOIN tasks t ON t.id=s.task_id WHERE t.project_id=?1 AND e.model=?2),
        (SELECT count(*) FROM embedding_jobs j JOIN tasks t ON t.id=j.task_id WHERE t.project_id=?1 AND j.model=?2)", &[project, model])?;
    let counts: Vec<usize> = row[0]
        .iter()
        .map(|s| s.parse().map_err(|_| Error::invalid("Invalid index count")))
        .collect::<Result<_>>()?;
    Ok(IndexStatus {
        sources: counts[0],
        ready: counts[1],
        pending: counts[2],
        complete: counts[0] == counts[1] && counts[2] == 0,
    })
}

fn validate_vector(vector: &[f32], dimensions: usize) -> Result<()> {
    if vector.len() != dimensions
        || vector.is_empty()
        || vector.iter().any(|v| !v.is_finite())
        || vector.iter().all(|v| *v == 0.0)
    {
        return Err(Error::invalid(
            "Embedding must have the configured dimension, finite values, and nonzero magnitude",
        ));
    }
    Ok(())
}

fn cosine(a: &[f32], b: &[f32]) -> f64 {
    let dot: f64 = a
        .iter()
        .zip(b)
        .map(|(a, b)| f64::from(*a) * f64::from(*b))
        .sum();
    let norm = |v: &[f32]| v.iter().map(|x| f64::from(*x).powi(2)).sum::<f64>().sqrt();
    (dot / (norm(a) * norm(b))).clamp(-1.0, 1.0)
}
