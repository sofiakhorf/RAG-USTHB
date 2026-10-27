-- ============================================
-- RAG-USTHB - Schéma SQL complet (Postgres + pgvector)
-- Généré pour partage avec une collaboratrice
-- ============================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

-- Types énumérés
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = 'public' AND t.typname = 'document_status'
  ) THEN
    CREATE TYPE public.document_status AS ENUM ('uploaded', 'processing', 'processed', 'failed');
  END IF;
  IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = 'public' AND t.typname = 'message_role'
  ) THEN
    CREATE TYPE public.message_role AS ENUM ('user', 'assistant', 'system');
  END IF;
END
$$;

-- Utilisateurs (lié à auth.users de Supabase)
CREATE TABLE IF NOT EXISTS public.users (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  auth_user_id UUID UNIQUE,
  email VARCHAR(255),
  full_name VARCHAR(255),
  role VARCHAR(50) DEFAULT 'student',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_auth_user_id ON public.users(auth_user_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON public.users(email);

-- Documents sources
CREATE TABLE IF NOT EXISTS public.documents (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  uploaded_by UUID REFERENCES public.users(id) ON DELETE SET NULL,
  original_filename VARCHAR(512) NOT NULL,
  stored_path TEXT,
  file_hash TEXT,
  family_type VARCHAR(10),
  mime_type VARCHAR(128),
  size_bytes BIGINT,
  status public.document_status NOT NULL DEFAULT 'uploaded',
  error_message TEXT,
  metadata JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_uploaded_by ON public.documents(uploaded_by);
CREATE INDEX IF NOT EXISTS idx_documents_family_type ON public.documents(family_type);
CREATE INDEX IF NOT EXISTS idx_documents_status ON public.documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_file_hash ON public.documents(file_hash);
CREATE INDEX IF NOT EXISTS idx_documents_metadata_gin ON public.documents USING GIN (metadata);

-- Chunks (issu du pipeline preprocessing / core.models)
CREATE TABLE IF NOT EXISTS public.chunks (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  document_id UUID REFERENCES public.documents(id) ON DELETE CASCADE,
  chunk_index INTEGER,
  text TEXT NOT NULL,
  document_name TEXT,
  family_type VARCHAR(10),
  procedure VARCHAR(255),
  formation VARCHAR(255),
  niveau VARCHAR(255),
  semestre VARCHAR(50),
  ue VARCHAR(255),
  matiere VARCHAR(255),
  annee_universitaire VARCHAR(50),
  page INTEGER,
  sheet_name VARCHAR(255),
  block_range VARCHAR(255),
  block_title VARCHAR(255),
  chapter VARCHAR(255),
  article_title VARCHAR(512),
  article_number INTEGER,
  language VARCHAR(10),
  is_fallback BOOLEAN DEFAULT FALSE,
  metadata JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON public.chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_family_type ON public.chunks(family_type);
CREATE INDEX IF NOT EXISTS idx_chunks_niveau ON public.chunks(niveau);
CREATE INDEX IF NOT EXISTS idx_chunks_semestre ON public.chunks(semestre);
CREATE INDEX IF NOT EXISTS idx_chunks_document_name ON public.chunks(document_name);
CREATE INDEX IF NOT EXISTS idx_chunks_page ON public.chunks(page);
CREATE INDEX IF NOT EXISTS idx_chunks_metadata_gin ON public.chunks USING GIN (metadata);

-- Embeddings
CREATE TABLE IF NOT EXISTS public.embeddings (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  chunk_id UUID NOT NULL REFERENCES public.chunks(id) ON DELETE CASCADE,
  embedding VECTOR(1536) NOT NULL,
  model_name VARCHAR(100),
  dimensions INTEGER,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(chunk_id)
);

CREATE INDEX IF NOT EXISTS idx_embeddings_vector_ivfflat ON public.embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Chat
CREATE TABLE IF NOT EXISTS public.chat_sessions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES public.users(id) ON DELETE SET NULL,
  title VARCHAR(255),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.chat_messages (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  session_id UUID NOT NULL REFERENCES public.chat_sessions(id) ON DELETE CASCADE,
  role public.message_role NOT NULL,
  content TEXT NOT NULL,
  context_chunks UUID[] DEFAULT '{}'::uuid[],
  sources JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id ON public.chat_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id ON public.chat_messages(session_id);

-- Triggers updated_at
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_users_updated_at ON public.users;
CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON public.users FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
DROP TRIGGER IF EXISTS trg_documents_updated_at ON public.documents;
CREATE TRIGGER trg_documents_updated_at BEFORE UPDATE ON public.documents FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
DROP TRIGGER IF EXISTS trg_chat_sessions_updated_at ON public.chat_sessions;
CREATE TRIGGER trg_chat_sessions_updated_at BEFORE UPDATE ON public.chat_sessions FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
