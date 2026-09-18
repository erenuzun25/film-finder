
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path
import sqlite3
import json

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "films.db"
HTML_FILE = BASE_DIR / "film_finder.html"

app = FastAPI(
    title="Film Finder",
    description="Film keşif ve öneri sistemi",
    version="1.0.0"
)


def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row):
    if row is None:
        return None

    data = dict(row)

    for key, value in data.items():
        if isinstance(value, bytes):
            data[key] = value.decode("utf-8", errors="ignore")

    return data


@app.get("/")
def root():
    return FileResponse(HTML_FILE)


@app.get("/film-finder")
def film_finder():
    return FileResponse(HTML_FILE)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "database": DB_FILE.exists(),
        "html": HTML_FILE.exists()
    }


@app.get("/api/stats")
def stats():
    conn = get_connection()

    try:
        movie_count = conn.execute(
            "SELECT COUNT(*) FROM movies"
        ).fetchone()[0]

        source_count = conn.execute(
            "SELECT COUNT(*) FROM movie_sources"
        ).fetchone()[0]

        return {
            "movies": movie_count,
            "sources": source_count
        }

    finally:
        conn.close()


@app.get("/api/search")
def search(q: str = ""):
    q = q.strip()

    if not q:
        return []

    conn = get_connection()

    try:
        rows = conn.execute(
            """
            SELECT
                id,
                title,
                original_title,
                year,
                rating,
                poster_url
            FROM movies
            WHERE title LIKE ?
               OR original_title LIKE ?
            ORDER BY rating DESC
            LIMIT 20
            """,
            (f"%{q}%", f"%{q}%")
        ).fetchall()

        return [row_to_dict(row) for row in rows]

    finally:
        conn.close()


@app.get("/api/movie/{movie_id}")
def movie_detail(movie_id: int):
    conn = get_connection()

    try:
        row = conn.execute(
            "SELECT * FROM movies WHERE id = ?",
            (movie_id,)
        ).fetchone()

        if row is None:
            raise HTTPException(
                status_code=404,
                detail="Film bulunamadı."
            )

        return row_to_dict(row)

    finally:
        conn.close()


@app.get("/api/filters")
def filters():
    conn = get_connection()

    try:
        rows = conn.execute(
            """
            SELECT genres
            FROM movies
            WHERE genres IS NOT NULL
              AND genres != ''
            """
        ).fetchall()

        genres = set()

        for row in rows:
            value = row["genres"]

            if not value:
                continue

            for genre in str(value).replace("|", ",").split(","):
                genre = genre.strip()

                if genre:
                    genres.add(genre)

        return {
            "genres": sorted(genres)
        }

    finally:
        conn.close()


class RecommendationRequest(BaseModel):
    selections: dict = {}


def contains_value(value, target):
    if value is None:
        return False

    value = str(value).lower()
    target = str(target).lower()

    return target in value


def score_movie(movie, selections):
    score = 0.0
    reasons = []

    genres = str(movie["genres"] or "").lower()
    description = str(movie["description"] or "").lower()
    story = str(movie["story"] or "").lower()
    themes = str(movie["themes"] or "").lower()

    text = " ".join([
        genres,
        description,
        story,
        themes
    ])

    # --------------------------------------------------------
    # Tür
    # --------------------------------------------------------

    selected_genres = selections.get("genre", [])

    if isinstance(selected_genres, str):
        selected_genres = [selected_genres]

    genre_matches = 0

    for genre in selected_genres:
        if contains_value(genres, genre):
            genre_matches += 1

    if selected_genres:
        if genre_matches:
            score += 25 * (
                genre_matches / len(selected_genres)
            )
            reasons.append("Seçtiğin türlerle uyumlu.")

    # --------------------------------------------------------
    # Tempo
    # --------------------------------------------------------

    pace = selections.get("pace")

    if pace:
        movie_pace = str(movie["pace"] or "").lower()

        if pace.lower() in movie_pace:
            score += 10
            reasons.append("İstediğin tempoya uygun.")

    # --------------------------------------------------------
    # Düşünme seviyesi
    # --------------------------------------------------------

    thinking = selections.get("thinking")

    if thinking:
        complexity = str(
            movie["complexity"] or ""
        ).lower()

        if thinking.lower() in complexity:
            score += 10
            reasons.append(
                "İstediğin düşünsel yoğunluğa uygun."
            )

    # --------------------------------------------------------
    # Aksiyon
    # --------------------------------------------------------

    action = selections.get("action")

    if action:
        action_level = str(
            movie["action_level"] or ""
        ).lower()

        if action.lower() in action_level:
            score += 8
            reasons.append("Aksiyon beklentine uygun.")

    # --------------------------------------------------------
    # Mizah
    # --------------------------------------------------------

    humor = selections.get("humor")

    if humor:
        comedy_level = str(
            movie["comedy_level"] or ""
        ).lower()

        if humor.lower() in comedy_level:
            score += 7
            reasons.append("Mizah tercihinle uyumlu.")

    # --------------------------------------------------------
    # Romantizm
    # --------------------------------------------------------

    romance = selections.get("romance")

    if romance:
        romance_level = str(
            movie["romance_level"] or ""
        ).lower()

        if romance.lower() in romance_level:
            score += 7
            reasons.append("Romantizm tercihinle uyumlu.")

    # --------------------------------------------------------
    # Ruh hali
    # --------------------------------------------------------

    mood = selections.get("mood")

    mood_words = {
        "dark": ["dark", "crime", "horror", "thriller"],
        "mysterious": ["mystery", "thriller"],
        "emotional": ["drama", "relationship"],
        "exciting": ["action", "thriller", "adventure"],
        "fun": ["comedy"],
        "epic": ["fantasy", "adventure", "war"],
        "strange": ["fantasy", "science fiction", "mystery"],
        "calm": ["drama", "relationship"]
    }

    if mood in mood_words:
        matches = 0

        for word in mood_words[mood]:
            if word in text:
                matches += 1

        if matches:
            score += min(12, matches * 4)
            reasons.append(
                "Seçtiğin atmosfere yakın."
            )

    # --------------------------------------------------------
    # Genel kalite katkısı
    # --------------------------------------------------------

    try:
        rating = float(movie["rating"] or 0)
    except Exception:
        rating = 0

    score += min(10, rating)

    if not reasons:
        reasons.append(
            "Genel film tercihlerinle uyumlu."
        )

    return score, reasons


@app.post("/api/recommend-smart")
def recommend_smart(request: RecommendationRequest):
    selections = request.selections or {}

    conn = get_connection()

    try:
        rows = conn.execute(
            """
            SELECT *
            FROM movies
            ORDER BY rating DESC
            """
        ).fetchall()

        results = []

        for row in rows:
            movie = row_to_dict(row)

            score, reasons = score_movie(
                movie,
                selections
            )

            movie["match_score"] = round(
                min(99.9, score),
                1
            )

            movie["recommendation_reason"] = (
                " ".join(reasons[:3])
            )

            results.append(movie)

        results.sort(
            key=lambda x: x["match_score"],
            reverse=True
        )

        return results[:5]

    finally:
        conn.close()


@app.get("/api/recommend")
def recommend():
    conn = get_connection()

    try:
        rows = conn.execute(
            """
            SELECT *
            FROM movies
            ORDER BY rating DESC
            LIMIT 5
            """
        ).fetchall()

        return [row_to_dict(row) for row in rows]

    finally:
        conn.close()
