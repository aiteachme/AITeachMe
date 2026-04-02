export interface ApiResponse<T> {
  code?: number;
  message?: string;
  data?: T | null;
}

export interface PaginatedData<T> {
  items?: T[];
  page?: number;
  size?: number;
  total?: number;
  pages?: number;
}
