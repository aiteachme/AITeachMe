package com.aiteachme.android.core.ui

import android.annotation.SuppressLint
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import java.net.URLEncoder

private val mermaidFenceRegex = Regex("""(?s)```mermaid\s*(.*?)```""")

sealed interface MarkdownDocumentBlock {
    data class Markdown(val content: String) : MarkdownDocumentBlock
    data class Mermaid(val chart: String) : MarkdownDocumentBlock
}

@Composable
fun MarkdownDocument(
    markdown: String,
    modifier: Modifier = Modifier,
    textSizeSp: Float = 16f,
) {
    val blocks = remember(markdown) { splitMarkdownDocument(markdown) }
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(14.dp)) {
        blocks.forEachIndexed { index, block ->
            when (block) {
                is MarkdownDocumentBlock.Markdown -> MarkdownText(
                    markdown = block.content,
                    modifier = Modifier.fillMaxWidth(),
                    color = MaterialTheme.colorScheme.onSurface,
                    linkColor = MaterialTheme.colorScheme.primary,
                    textSizeSp = textSizeSp,
                    selectable = true,
                )
                is MarkdownDocumentBlock.Mermaid -> MermaidWebBlock(
                    chart = block.chart,
                    modifier = Modifier.fillMaxWidth(),
                    key = index,
                )
            }
        }
    }
}

@SuppressLint("SetJavaScriptEnabled")
@Composable
private fun MermaidWebBlock(
    chart: String,
    modifier: Modifier = Modifier,
    key: Int,
) {
    Surface(
        modifier = modifier,
        color = MaterialTheme.colorScheme.surfaceContainer,
        shape = MaterialTheme.shapes.large,
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(12.dp)) {
            Text("Mermaid 图表", style = MaterialTheme.typography.titleSmall)
            AndroidView(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(320.dp),
                factory = { context ->
                    WebView(context).apply {
                        webViewClient = WebViewClient()
                        settings.javaScriptEnabled = true
                        settings.domStorageEnabled = true
                        setBackgroundColor(android.graphics.Color.TRANSPARENT)
                    }
                },
                update = { webView ->
                    webView.loadDataWithBaseURL(
                        "https://cdn.jsdelivr.net/",
                        buildMermaidHtml(chart, key),
                        "text/html",
                        "UTF-8",
                        null,
                    )
                },
            )
        }
    }
}

private fun splitMarkdownDocument(markdown: String): List<MarkdownDocumentBlock> {
    if (markdown.isBlank()) return emptyList()
    val blocks = mutableListOf<MarkdownDocumentBlock>()
    var cursor = 0
    mermaidFenceRegex.findAll(markdown).forEach { match ->
        if (match.range.first > cursor) {
            markdown.substring(cursor, match.range.first).takeIf { it.isNotBlank() }?.let {
                blocks += MarkdownDocumentBlock.Markdown(it)
            }
        }
        blocks += MarkdownDocumentBlock.Mermaid(match.groupValues[1].trim())
        cursor = match.range.last + 1
    }
    if (cursor < markdown.length) {
        markdown.substring(cursor).takeIf { it.isNotBlank() }?.let {
            blocks += MarkdownDocumentBlock.Markdown(it)
        }
    }
    return blocks
}

private fun buildMermaidHtml(chart: String, key: Int): String {
    val encoded = URLEncoder.encode(chart, Charsets.UTF_8.name()).replace("+", "%20")
    return """
        <!doctype html>
        <html>
        <head>
          <meta name="viewport" content="width=device-width, initial-scale=1" />
          <style>
            body { margin: 0; background: transparent; font-family: sans-serif; }
            .wrap { min-height: 300px; display: flex; align-items: center; justify-content: center; }
            .mermaid { width: 100%; }
            pre { white-space: pre-wrap; color: #334155; font-size: 13px; }
          </style>
          <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
        </head>
        <body>
          <div class="wrap"><pre id="fallback"></pre><div class="mermaid" id="chart"></div></div>
          <script>
            const source = decodeURIComponent("$encoded");
            document.getElementById("fallback").textContent = source;
            const target = document.getElementById("chart");
            target.textContent = source;
            try {
              mermaid.initialize({ startOnLoad: false, securityLevel: "loose" });
              mermaid.run({ nodes: [target] }).then(() => {
                document.getElementById("fallback").style.display = "none";
              });
            } catch (error) {}
          </script>
        </body>
        </html>
    """.trimIndent()
}
