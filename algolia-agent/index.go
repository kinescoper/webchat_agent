// index.go — загрузка всех .md из docs_crawl в Algolia (batch).
package main

import (
	"log"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/algolia/algoliasearch-client-go/v4/algolia/search"
)

const (
	batchSize      = 1000
	maxRecordBytes = 7000 // Algolia limit 10KB per record (JSON); content chunk size to leave room for objectID, source, section, title
)

func indexDocsToAlgolia(client *search.APIClient, docsDir, indexName string) error {
	docsDir = filepath.Clean(docsDir)
	if _, err := os.Stat(docsDir); os.IsNotExist(err) {
		log.Fatalf("DOCS_DIR not found: %s", docsDir)
	}

	var requests []search.BatchRequest
	var count int

	err := filepath.Walk(docsDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if info.IsDir() || !strings.HasSuffix(strings.ToLower(path), ".md") {
			return nil
		}
		body, err := os.ReadFile(path)
		if err != nil {
			log.Printf("skip %s: %v", path, err)
			return nil
		}
		content := string(body)
		rel, _ := filepath.Rel(docsDir, path)
		rel = filepath.ToSlash(rel)
		section := filepath.ToSlash(filepath.Dir(rel))
		var source string
		if filepath.Base(path) == "index.md" {
			source = "https://docs.kinescope.ru/" + section
		} else {
			source = "https://docs.kinescope.ru/" + strings.TrimSuffix(rel, ".md")
		}
		title := extractTitle(content)
		chunks := chunkContent(content, maxRecordBytes)

		for i, chunk := range chunks {
			objectID := rel
			if len(chunks) > 1 {
				objectID = rel + "#" + itoa(i)
			}
			requests = append(requests, search.BatchRequest{
				Action: search.ACTION_ADD_OBJECT,
				Body: map[string]any{
					"objectID": objectID,
					"content":  chunk,
					"source":   source,
					"section":  section,
					"title":    title,
				},
			})
			count++

			if len(requests) >= batchSize {
				if err := sendBatch(client, indexName, requests); err != nil {
					return err
				}
				requests = requests[:0]
			}
		}
		return nil
	})
	if err != nil {
		return err
	}
	if len(requests) > 0 {
		if err := sendBatch(client, indexName, requests); err != nil {
			return err
		}
	}
	log.Printf("Indexed %d records to index %q", count, indexName)
	return nil
}

func itoa(i int) string { return strconv.Itoa(i) }

// chunkContent splits content into chunks under maxBytes (by runes to avoid cutting multi-byte chars).
func chunkContent(content string, maxBytes int) []string {
	if len(content) <= maxBytes {
		return []string{content}
	}
	var chunks []string
	for len(content) > 0 {
		n := maxBytes
		if n > len(content) {
			n = len(content)
		} else {
			// try to break at newline
			if idx := strings.LastIndex(content[:n], "\n"); idx > maxBytes/2 {
				n = idx + 1
			}
		}
		chunks = append(chunks, content[:n])
		content = content[n:]
	}
	return chunks
}

func extractTitle(content string) string {
	lines := strings.SplitN(content, "\n", 20)
	for _, line := range lines {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "# Source:") {
			continue
		}
		if strings.HasPrefix(line, "# ") {
			return strings.TrimSpace(strings.TrimPrefix(line, "# "))
		}
	}
	return ""
}

func sendBatch(client *search.APIClient, indexName string, requests []search.BatchRequest) error {
	params := search.NewBatchWriteParams(requests)
	req := client.NewApiBatchRequest(indexName, params)
	_, err := client.Batch(req)
	if err != nil {
		return err
	}
	log.Printf("  batch %d records ok", len(requests))
	return nil
}
