export interface FileAssetItem {
  name: string;
  url: string;
  mime_type?: string | null;
}

export interface FileRecord {
  id: string;
  filename: string;
  filetype: string;
  status: string;
  ingest_status: string;
  markdown_ready: boolean;
  asset_ready: boolean;
  error_message?: string | null;
  file_size_bytes?: number | null;
  detected_language?: string | null;
  estimated_pages?: number | null;
  image_count?: number | null;
  parser_used?: string | null;
  markdown_content?: string;
  asset_base_url?: string | null;
  assets?: FileAssetItem[];
  latest_updated_at: string;
  created_at: string;
}

export interface FileMarkdownChunk {
  content: string;
  offset: number;
  next_offset: number;
  total_chars: number;
  done: boolean;
}

export interface FilesData {
  course_id?: string | null;
  total: number;
  ready_count: number;
  processing_count: number;
  failed_count: number;
  items: FileRecord[];
}

export interface FilesUploadData {
  course_id?: string | null;
  filenames: string[];
  uploaded_items: FileRecord[];
  started_parse_count: number;
}
