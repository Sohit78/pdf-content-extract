export type OcrMode = "off" | "auto" | "force";
export type OcrBackend = "gcv" | "trocr";

export interface ExtractionOptions {
  include_text: boolean;
  include_tables: boolean;
  include_images: boolean;
  include_image_bytes: boolean;
  include_metadata: boolean;
  ocr_mode: OcrMode;
  ocr_backend: OcrBackend;
  ocr_zoom: number;
  page_start: number | "";
  page_end: number | "";
}

export interface TextItem {
  page: number;
  content: string;
}

export interface TableItem {
  page: number;
  table_index: number;
  rows: (string | null)[][];
}

export interface ImageItem {
  /** First page the image appears on. */
  page: number;
  /** Every page it appears on — repeated logos collapse into one record. */
  pages?: number[];
  occurrences?: number;
  image_index: number;
  ext?: string;
  mime_type?: string;
  size_bytes?: number;
  sha256?: string;
  /** Absent when include_image_bytes is off. */
  bytes_base64?: string;
  width?: number;
  height?: number;
}

export interface DocumentMetadata {
  title?: string | null;
  author?: string | null;
  subject?: string | null;
  keywords?: string | null;
  creator?: string | null;
  producer?: string | null;
  created?: string | null;
  modified?: string | null;
  format?: string | null;
  encrypted?: boolean;
}

export interface OutlineItem {
  level: number;
  title: string;
  page: number;
}

export interface LinkItem {
  page: number;
  kind: "internal" | "external";
  uri?: string;
  target_page?: number;
}

export interface DocumentInfo {
  metadata: DocumentMetadata;
  outline: OutlineItem[];
  links: LinkItem[];
  page_size?: { width: number; height: number; rotation: number } | null;
}

export interface ExtractionResponse {
  source_url: string;
  extracted_at: string;
  page_count: number;
  total_pages: number;
  text: TextItem[];
  tables: TableItem[];
  images: ImageItem[];
  document?: DocumentInfo;
  meta?: {
    selected_pages?: number[];
    processing_ms?: number;
    cache?: "hit" | "miss";
    ocr?: { performed: number; cached: number };
    options?: Record<string, unknown>;
  };
}
