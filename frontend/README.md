# AI TEACHE ME

A modern SaaS-style learning platform powered by AI.

## Tech Stack

- React 18
- TypeScript
- Vite
- TailwindCSS
- React Router
- Lucide Icons

## Features

- 📚 Subject Management - Create and manage multiple subjects
- 📤 Upload Materials - Upload course materials and notes
- 📝 Knowledge Summary - AI-generated summaries and mind maps
- 💬 AI Chat - Interactive learning assistant
- 📋 Exam Prediction - Practice with AI-generated questions
- 📊 Learning Analytics - Track progress and performance

## Getting Started

### Prerequisites

Make sure you have Node.js installed (v18 or higher recommended).

### Installation

1. Install dependencies:

```bash
npm install
```

2. Start the development server:

```bash
npm run dev
```

3. Open your browser and navigate to `http://localhost:5173`

### Build for Production

```bash
npm run build
```

The built files will be in the `dist` directory.

## Project Structure

```
src/
├── components/
│   ├── ui/              # Reusable UI components
│   │   ├── Button.tsx
│   │   └── Card.tsx
│   ├── pages/           # Page components
│   │   ├── HomePage.tsx
│   │   ├── UploadPage.tsx
│   │   ├── SummaryPage.tsx
│   │   ├── ChatPage.tsx
│   │   ├── ExamPage.tsx
│   │   └── AnalysisPage.tsx
│   ├── Layout.tsx       # Main layout wrapper
│   └── Sidebar.tsx      # Navigation sidebar
├── lib/
│   └── utils.ts         # Utility functions
├── App.tsx              # Main app with routing
├── main.tsx             # Entry point
└── index.css            # Global styles
```

## Design Philosophy

The UI follows modern SaaS design principles:

- Clean, minimal layout with plenty of whitespace
- Soft shadows and rounded corners
- Responsive design (mobile-friendly)
- Inspired by Linear, Notion, and ChatGPT

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `VITE_API_URL` | Backend API URL | `http://localhost:8000` |

## Deployment

### Vercel

The frontend can be deployed to Vercel:

1. Connect your GitHub repository
2. Set the framework preset to Vite
3. Configure environment variables in the Vercel dashboard
4. Deploy

## License

Private project

