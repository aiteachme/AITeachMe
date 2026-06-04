package com.aiteachme.android.core.ui

import android.text.method.LinkMovementMethod
import android.text.TextUtils
import android.util.TypedValue
import android.view.ViewGroup
import android.widget.TextView
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import io.noties.markwon.Markwon
import io.noties.markwon.ext.latex.JLatexMathPlugin
import io.noties.markwon.ext.tables.TablePlugin
import io.noties.markwon.html.HtmlPlugin
import io.noties.markwon.inlineparser.MarkwonInlineParserPlugin

@Composable
fun MarkdownText(
    markdown: String,
    modifier: Modifier = Modifier,
    color: Color = Color.Unspecified,
    linkColor: Color = Color.Unspecified,
    textSizeSp: Float = 16f,
    selectable: Boolean = false,
    maxLines: Int? = null,
) {
    val context = LocalContext.current
    val latexTextSizePx = remember(context, textSizeSp) {
        TypedValue.applyDimension(
            TypedValue.COMPLEX_UNIT_SP,
            textSizeSp,
            context.resources.displayMetrics,
        )
    }
    val markwon = remember(context, latexTextSizePx) {
        Markwon.builder(context)
            .usePlugin(HtmlPlugin.create())
            .usePlugin(TablePlugin.create(context))
            .usePlugin(MarkwonInlineParserPlugin.create())
            .usePlugin(
                JLatexMathPlugin.create(latexTextSizePx) { builder ->
                    builder.inlinesEnabled(true)
                },
            )
            .build()
    }
    val textColor = color.takeOrElse(Color.Black).toArgb()
    val resolvedLinkColor = linkColor.takeOrElse(Color(0xFF0B72FF)).toArgb()
    val normalizedMarkdown = remember(markdown) {
        normalizeLatexDelimiters(markdown)
    }

    AndroidView(
        modifier = modifier,
        factory = { viewContext ->
            TextView(viewContext).apply {
                layoutParams = ViewGroup.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                )
                includeFontPadding = true
                movementMethod = LinkMovementMethod.getInstance()
                setTextIsSelectable(selectable)
                setPadding(0, 0, 0, 0)
            }
        },
        update = { textView ->
            textView.setTextColor(textColor)
            textView.setLinkTextColor(resolvedLinkColor)
            textView.setTextSize(TypedValue.COMPLEX_UNIT_SP, textSizeSp)
            textView.setTextIsSelectable(selectable)
            textView.maxLines = maxLines ?: Int.MAX_VALUE
            textView.ellipsize = if (maxLines == null) null else TextUtils.TruncateAt.END
            markwon.setMarkdown(textView, normalizedMarkdown)
        },
    )
}

private val fencedCodeRegex = Regex("""(?s)(```.*?```|~~~.*?~~~)""")
private val displayBracketMathRegex = Regex("""\\\[([\s\S]*?)\\\]""")
private val inlineParenMathRegex = Regex("""\\\(([\s\S]*?)\\\)""")
private val latexEnvironmentRegex = Regex(
    """\\begin\{(equation\*?|align\*?|gather\*?|multline\*?)\}([\s\S]*?)\\end\{\1\}""",
)

private fun normalizeLatexDelimiters(markdown: String): String {
    if (markdown.isBlank()) {
        return markdown
    }

    val builder = StringBuilder(markdown.length)
    var cursor = 0
    fencedCodeRegex.findAll(markdown).forEach { match ->
        if (match.range.first > cursor) {
            builder.append(normalizeLatexSegment(markdown.substring(cursor, match.range.first)))
        }
        builder.append(match.value)
        cursor = match.range.last + 1
    }
    if (cursor < markdown.length) {
        builder.append(normalizeLatexSegment(markdown.substring(cursor)))
    }
    return builder.toString()
}

private fun normalizeLatexSegment(segment: String): String {
    return latexEnvironmentRegex
        .replace(segment) { match ->
            "\n\n${'$'}${'$'}\n${match.groupValues[2].trim()}\n${'$'}${'$'}\n\n"
        }
        .let { normalized ->
            displayBracketMathRegex.replace(normalized) { match ->
                "\n\n${'$'}${'$'}\n${match.groupValues[1].trim()}\n${'$'}${'$'}\n\n"
            }
        }
        .let { normalized ->
            inlineParenMathRegex.replace(normalized) { match ->
                "${'$'}${match.groupValues[1].trim()}${'$'}"
            }
        }
}

private fun Color.takeOrElse(fallback: Color): Color {
    return if (this == Color.Unspecified) fallback else this
}
