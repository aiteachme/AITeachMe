import { defineConfig } from "orval"

export default defineConfig({
    api: {
        input: "./openapi.json",

        output: {
            mode: "tags",

            target: "./src/api/generated",

            schemas: "./src/api/generated/model",

            client: "react-query",
            httpClient: "axios",

            override: {
                mutator: {
                    path: "./src/api/client.ts",
                    name: "apiClient",
                },
            },
        },
    },
})