# RAG-USTHB

A prototype interface for an academic assistant designed for students of the University of Sciences and Technology Houari Boumediene (USTHB). The project aims to organize course materials and academic documents, laying the groundwork for a future search and study experience powered by Retrieval-Augmented Generation (RAG).

> **Project Status:** This is a Minimum Viable Product (MVP) preview interface. There is currently no connected RAG engine, artificial intelligence model, database, or backend authentication service.

## Current Features

- Landing page and full Arabic interface with right-to-left (RTL) layout support.
- Demo chat interface with sample subjects, conversations, and documents.
- Content organization by academic subject (e.g., Algorithms, Analysis, Algebra, Physics).
- Local file attachment preview supporting standard document formats (PDF, DOC, DOCX, TXT, MD) up to 10 MB per file.
- Theme switching support for light and dark modes.

## Prototype Limitations

- Questions are not dispatched to an AI model or retrieval engine; a static explanatory message is shown instead of a generated response.
- Chat history, documents, and subject data are strictly mock data stored only within the front-end state.
- Login and registration interfaces are mock UI components and are not tied to an active authentication service.
- Uploaded files remain strictly local within the current preview session and are neither stored permanently nor transmitted to a server.

Do not use this prototype to submit sensitive personal information or official university documents.

## Tech Stack

- Next.js 16 (App Router)
- React 19
- Tailwind CSS 4
- pnpm

## Prerequisites

- Node.js version compatible with Next.js 16
- pnpm package manager

## Local Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/sofiakhorf/RAG-USTHB
   ```

2. Navigate into the project directory:
   ```bash
   cd "RAG-USTHB\frontend"
   ```

3. Install project dependencies:
   ```bash
   pnpm install
   ```

4. Start the development server:
   ```bash
   pnpm dev
   ```

5. Open [http://localhost:3000](http://localhost:3000) in your browser.

## Build & Production Commands

- **Build the application:**
  ```bash
  pnpm build
  ```

- **Run production build:**
  ```bash
  pnpm start
  ```

## Project Structure

- `app/page.jsx`: Main application layout, view flow routing, and prototype preview state.
- `app/mock-data.js`: Mock subjects, conversations, and document data.
- `app/rag-*.jsx`: Interface components, including home landing page, chat feed, sidebar, and attachment dialogs.
- `public/`: Static assets and public images.
- `lib/`: Helper functions and shared utilities.

## Development via v0

This repository is linked to a v0 workspace. Continuous UI iterations and visual enhancements can be followed directly through the v0 project page.