// Algolia agent: минимальный HTTP-сервис с клиентом Algolia (v4).
// Переменные: ALGOLIA_APPLICATION_ID, ALGOLIA_API_KEY.
// Эндпоинты: GET /health, GET /search?q=...&index=... (опционально).
package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
	"path/filepath"

	"github.com/algolia/algoliasearch-client-go/v4/algolia/search"
	"github.com/joho/godotenv"
)

func main() {
	// Загрузить .env из текущей папки и из родителя (корень проекта)
	if exec, _ := os.Executable(); exec != "" {
		dir := filepath.Dir(exec)
		_ = godotenv.Load(filepath.Join(dir, ".env"))
		_ = godotenv.Load(filepath.Join(dir, "..", ".env"))
	}
	_ = godotenv.Load(".env")
	_ = godotenv.Load("../.env")

	appID := os.Getenv("ALGOLIA_APPLICATION_ID")
	apiKey := os.Getenv("ALGOLIA_API_KEY")
	if appID == "" || apiKey == "" {
		log.Println("ALGOLIA_APPLICATION_ID and ALGOLIA_API_KEY are required")
	}

	client, err := search.NewClient(appID, apiKey)
	if err != nil {
		log.Fatalf("Algolia client: %v", err)
	}

	// Subcommand: index — загрузить все .md из docs_crawl в Algolia
	if len(os.Args) > 1 && os.Args[1] == "index" {
		docsDir := os.Getenv("ALGOLIA_DOCS_DIR")
		if docsDir == "" {
			docsDir = "docs_crawl"
		}
		indexName := os.Getenv("ALGOLIA_INDEX_NAME")
		if indexName == "" {
			indexName = "kinescope_docs"
		}
		if err := indexDocsToAlgolia(client, docsDir, indexName); err != nil {
			log.Fatalf("index: %v", err)
		}
		return
	}

	http.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"status": "ok", "algolia": "configured"})
	})

	http.HandleFunc("/search", func(w http.ResponseWriter, r *http.Request) {
		if appID == "" || apiKey == "" {
			http.Error(w, `{"error":"algolia not configured"}`, http.StatusServiceUnavailable)
			return
		}
		q := r.URL.Query().Get("q")
		indexName := r.URL.Query().Get("index")
		if indexName == "" {
			indexName = "content"
		}
		if q == "" {
			http.Error(w, `{"error":"missing q"}`, http.StatusBadRequest)
			return
		}
		params := search.SearchParamsObjectAsSearchParams(&search.SearchParamsObject{Query: &q})
		req := client.NewApiSearchSingleIndexRequest(indexName).WithSearchParams(params)
		res, err := client.SearchSingleIndex(req, search.WithContext(r.Context()))
		if err != nil {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusBadGateway)
			json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
			return
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(res)
	})

	addr := os.Getenv("ALGOLIA_AGENT_ADDR")
	if addr == "" {
		addr = ":8080"
	}
	log.Printf("Algolia agent listening on %s", addr)
	log.Fatal(http.ListenAndServe(addr, nil))
}
