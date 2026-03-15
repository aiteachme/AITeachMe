# AGENTS.md

This project is an AI-first frontend project.

## Execution Rules

- Do NOT ask for confirmation for normal coding tasks.
- Only ask for confirmation for dangerous operations:
    - deleting files
    - modifying environment configs
    - database changes

All other tasks should execute directly.

---

## Frontend Stack

- React
- TypeScript
- Vite
- TailwindCSS
- shadcn/ui

---

## Code Quality

Follow these rules:

1. Components must be small and reusable
   2. Avoid inline styles
3. Use TailwindCSS for styling
4. Use functional components
5. Use clear naming

---

## UI Requirements

UI style should follow modern SaaS design:

- clean layout
- large whitespace
- card-based design
- subtle shadows
- rounded corners

Inspired by:

- Linear
- Notion
- ChatGPT

---

## Responsiveness

The UI must support:

- Desktop
- Tablet
- Mobile

Use responsive layouts.

---

## Folder Rules

Pages go to:

src/pages/

Reusable components:

src/components/

Hooks:

src/hooks/