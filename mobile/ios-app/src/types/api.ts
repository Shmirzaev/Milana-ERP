export type Me = {
  id: number;
  name: string;
  email: string;
  role?: string | null;
  department?: string | null;
  permissions: string[];
  extra_permissions?: string[];
};

export type Entity = Record<string, unknown> & {
  id?: number;
  status?: string;
};

export type ListEnvelope = {
  rows?: Entity[];
  items?: Entity[];
  total?: number;
  page?: number;
  page_size?: number;
};

export type SearchResult = {
  type: string;
  id: number;
  label: string;
  url: string;
};
