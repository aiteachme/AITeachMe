import { defineConfig } from "orval"

export default defineConfig({
    api: {
        input: "./openapi.json",

        output: {
            mode: "tags",

            target: "./src/api/generated",
            client: "react-query",
            clean: true,
        },
    },
})
