package com.aiteachme.android.feature.course.presentation

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.Insights
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.aiteachme.android.core.network.dto.FullGraphResponse
import com.aiteachme.android.core.network.dto.GraphEdgeResponse
import com.aiteachme.android.core.network.dto.KnowledgeRelationResponse
import com.aiteachme.android.core.network.dto.KnowledgeUnitDetailResponse
import com.aiteachme.android.core.network.dto.KnowledgeUnitResponse
import com.aiteachme.android.core.ui.MarkdownText
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

@Composable
fun KnowledgeGraphScreen(
    courseId: String,
    contentPadding: PaddingValues,
    onBack: () -> Unit,
    onOpenDocs: (String) -> Unit,
    viewModel: KnowledgeGraphViewModel = viewModel(),
) {
    val state by viewModel.uiState.collectAsState()

    LaunchedEffect(courseId) {
        viewModel.load(courseId)
    }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(contentPadding),
        contentPadding = PaddingValues(horizontal = 20.dp, vertical = 18.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item {
            KnowledgeGraphHeader(
                graph = state.graph,
                isLoading = state.isLoading,
                isBuildingGraph = state.isBuildingGraph,
                onBack = onBack,
                onRefresh = { viewModel.load(courseId) },
                onBuildGraph = { viewModel.startGraphBuild(courseId) },
            )
        }

        item {
            Button(
                onClick = { viewModel.startGraphBuild(courseId) },
                enabled = !state.isBuildingGraph,
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (state.isBuildingGraph) {
                    CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                    Spacer(modifier = Modifier.width(8.dp))
                }
                Text(if (state.isBuildingGraph) "正在启动图谱构建" else "重建知识图谱")
            }
        }

        state.errorMessage?.let { message ->
            item {
                GraphMessageCard(message = message, isError = true)
            }
        }
        state.infoMessage?.let { message ->
            item {
                GraphMessageCard(message = message, isError = false)
            }
        }

        if (state.isLoading && state.graph.nodes.isEmpty()) {
            item { GraphLoadingCard() }
        } else if (state.graph.nodes.isEmpty()) {
            item {
                EmptyGraphCard(onOpenDocs = { onOpenDocs(courseId) })
            }
        } else {
            item {
                KnowledgeGraphCanvasCard(
                    graph = state.graph,
                    selectedNodeId = state.selectedNodeId,
                    onNodeSelected = { nodeId -> viewModel.selectNode(courseId, nodeId) },
                )
            }

            val selectedNode = state.selectedNodeId
                ?.let { id -> state.graph.nodes.firstOrNull { node -> node.id == id } }
            if (selectedNode != null) {
                item {
                    KnowledgeGraphNodeDetail(
                        graph = state.graph,
                        node = selectedNode,
                        detail = state.selectedDetail,
                        relations = state.selectedRelations,
                        isLoadingDetail = state.isLoadingDetail,
                        onClose = { viewModel.selectNode(null) },
                        onNodeSelected = { nodeId -> viewModel.selectNode(courseId, nodeId) },
                    )
                }
            }

            item {
                Text("知识节点", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            }
            items(state.graph.nodes.sortedBy { it.canonicalName }, key = { it.id }) { node ->
                KnowledgeNodeListItem(
                    node = node,
                    selected = state.selectedNodeId == node.id,
                    relationCount = state.graph.degreeOf(node.id),
                    onClick = { viewModel.selectNode(courseId, node.id) },
                )
            }
        }
    }
}

@Composable
private fun KnowledgeGraphHeader(
    graph: FullGraphResponse,
    isLoading: Boolean,
    isBuildingGraph: Boolean,
    onBack: () -> Unit,
    onRefresh: () -> Unit,
    onBuildGraph: () -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surfaceContainer,
        shape = MaterialTheme.shapes.large,
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Top,
            ) {
                IconButton(onClick = onBack, modifier = Modifier.size(40.dp)) {
                    Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "返回")
                }
                OutlinedButton(onClick = onRefresh, enabled = !isLoading) {
                    if (isLoading) {
                        CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                    } else {
                        Icon(Icons.Outlined.Refresh, contentDescription = null, modifier = Modifier.size(16.dp))
                    }
                    Spacer(modifier = Modifier.width(6.dp))
                    Text("刷新")
                }
            }
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(
                    text = "知识图谱",
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Black,
                )
                Text(
                    text = "动态展示当前学科知识点和依赖关系，数据来自本课程的知识图谱接口。",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                GraphStatChip(label = "节点", value = graph.nodes.size.toString(), modifier = Modifier.weight(1f))
                GraphStatChip(label = "关系", value = graph.edges.size.toString(), modifier = Modifier.weight(1f))
                GraphStatChip(label = "类型", value = graph.nodes.map { it.knowledgeUnitType }.distinct().size.toString(), modifier = Modifier.weight(1f))
            }
        }
    }
}

@Composable
private fun GraphStatChip(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier,
        color = MaterialTheme.colorScheme.surface,
        shape = MaterialTheme.shapes.medium,
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
            verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            Text(value, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(label, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun KnowledgeGraphCanvasCard(
    graph: FullGraphResponse,
    selectedNodeId: Int?,
    onNodeSelected: (Int) -> Unit,
) {
    val visibleNodes = remember(graph.nodes, graph.edges, selectedNodeId) {
        graph.visibleGraphNodes(selectedNodeId)
    }
    val positions = remember(visibleNodes) {
        calculateGraphPositions(visibleNodes)
    }
    val visibleIds = remember(visibleNodes) { visibleNodes.map { it.id }.toSet() }

    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surface,
        shape = MaterialTheme.shapes.large,
        tonalElevation = 1.dp,
    ) {
        Column(
            modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Outlined.Insights, contentDescription = null, modifier = Modifier.size(18.dp))
                    Text("图谱视图", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                }
                Text(
                    text = "显示 ${visibleNodes.size}/${graph.nodes.size}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            BoxWithConstraints(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(360.dp)
                    .clip(RoundedCornerShape(18.dp))
                    .background(MaterialTheme.colorScheme.surfaceContainer),
            ) {
                val graphHeight = 360.dp
                Canvas(modifier = Modifier.fillMaxSize()) {
                    graph.edges
                        .filter { edge -> edge.sourceNodeId in visibleIds && edge.targetNodeId in visibleIds }
                        .forEach { edge ->
                            val source = positions[edge.sourceNodeId] ?: return@forEach
                            val target = positions[edge.targetNodeId] ?: return@forEach
                            val selected = selectedNodeId == edge.sourceNodeId || selectedNodeId == edge.targetNodeId
                            drawLine(
                                color = if (selected) Color(0xFF2563EB) else Color(0x668B95A1),
                                start = Offset(source.x * size.width, source.y * size.height),
                                end = Offset(target.x * size.width, target.y * size.height),
                                strokeWidth = if (selected) 4f else 2f,
                                cap = StrokeCap.Round,
                            )
                        }
                }

                visibleNodes.forEach { node ->
                    val position = positions[node.id] ?: return@forEach
                    GraphNodeBubble(
                        node = node,
                        selected = selectedNodeId == node.id,
                        modifier = Modifier.offset(
                            x = maxWidth * position.x - 43.dp,
                            y = graphHeight * position.y - 24.dp,
                        ),
                        onClick = { onNodeSelected(node.id) },
                    )
                }
            }
            GraphLegend()
        }
    }
}

@Composable
private fun GraphNodeBubble(
    node: KnowledgeUnitResponse,
    selected: Boolean,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    val tone = nodeTypeTone(node.knowledgeUnitType)
    Surface(
        modifier = modifier
            .width(86.dp)
            .height(48.dp)
            .clickable(onClick = onClick),
        color = if (selected) MaterialTheme.colorScheme.primary else tone.background,
        contentColor = if (selected) MaterialTheme.colorScheme.onPrimary else tone.content,
        shape = RoundedCornerShape(14.dp),
        tonalElevation = if (selected) 4.dp else 1.dp,
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 6.dp),
            verticalArrangement = Arrangement.Center,
        ) {
            Text(
                text = node.canonicalName,
                style = MaterialTheme.typography.labelMedium,
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = nodeTypeLabel(node.knowledgeUnitType),
                style = MaterialTheme.typography.labelSmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun GraphLegend() {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        listOf("concept", "method", "example").forEach { type ->
            val tone = nodeTypeTone(type)
            Surface(color = tone.background, contentColor = tone.content, shape = CircleShape) {
                Text(
                    text = nodeTypeLabel(type),
                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
                    style = MaterialTheme.typography.labelSmall,
                )
            }
        }
    }
}

@Composable
private fun KnowledgeNodeListItem(
    node: KnowledgeUnitResponse,
    selected: Boolean,
    relationCount: Int,
    onClick: () -> Unit,
) {
    val tone = nodeTypeTone(node.knowledgeUnitType)
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        color = if (selected) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceContainer,
        shape = MaterialTheme.shapes.large,
    ) {
        Row(
            modifier = Modifier.padding(14.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Surface(
                modifier = Modifier.size(40.dp),
                color = tone.background,
                contentColor = tone.content,
                shape = CircleShape,
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Text(nodeTypeInitial(node.knowledgeUnitType), fontWeight = FontWeight.Bold)
                }
            }
            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                MarkdownText(
                    markdown = node.canonicalName,
                    textSizeSp = 15f,
                    color = MaterialTheme.colorScheme.onSurface,
                    linkColor = MaterialTheme.colorScheme.primary,
                    maxLines = 1,
                )
                Text(
                    text = "${nodeTypeLabel(node.knowledgeUnitType)} · $relationCount 条关系 · 置信度 ${formatPercent(node.confidence)}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

@Composable
private fun KnowledgeGraphNodeDetail(
    graph: FullGraphResponse,
    node: KnowledgeUnitResponse,
    detail: KnowledgeUnitDetailResponse?,
    relations: List<KnowledgeRelationResponse>,
    isLoadingDetail: Boolean,
    onClose: () -> Unit,
    onNodeSelected: (Int) -> Unit,
) {
    val incidentEdges = remember(graph.edges, node.id) {
        graph.edges.filter { edge -> edge.sourceNodeId == node.id || edge.targetNodeId == node.id }
    }
    val nodeById = remember(graph.nodes) { graph.nodes.associateBy { it.id } }

    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surface,
        shape = MaterialTheme.shapes.large,
        tonalElevation = 1.dp,
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Top,
            ) {
                Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    MarkdownText(
                        markdown = node.canonicalName,
                        textSizeSp = 18f,
                        color = MaterialTheme.colorScheme.onSurface,
                        linkColor = MaterialTheme.colorScheme.primary,
                    )
                    Text(
                        text = "${nodeTypeLabel(node.knowledgeUnitType)} · ${node.status.ifBlank { "active" }} · 置信度 ${formatPercent(node.confidence)}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                IconButton(onClick = onClose, modifier = Modifier.size(36.dp)) {
                    Icon(Icons.Outlined.Close, contentDescription = "关闭")
                }
            }

            if (isLoadingDetail) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                    Text("正在加载节点证据和关系...", style = MaterialTheme.typography.bodySmall)
                }
            }

            detail?.currentRevision?.let { revision ->
                if (revision.summary.isNotBlank() || revision.body.isNotBlank()) {
                    Surface(color = MaterialTheme.colorScheme.surfaceContainer, shape = MaterialTheme.shapes.medium) {
                        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            if (revision.summary.isNotBlank()) {
                                MarkdownText(
                                    markdown = revision.summary,
                                    textSizeSp = 14f,
                                    color = MaterialTheme.colorScheme.onSurface,
                                    linkColor = MaterialTheme.colorScheme.primary,
                                )
                            }
                            if (revision.body.isNotBlank()) {
                                MarkdownText(
                                    markdown = revision.body,
                                    textSizeSp = 13f,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    linkColor = MaterialTheme.colorScheme.primary,
                                    maxLines = 6,
                                )
                            }
                        }
                    }
                }
            }

            if (detail?.sourceRefs?.isNotEmpty() == true) {
                Text("证据来源", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                detail.sourceRefs.take(3).forEach { source ->
                    GraphMessageCard(
                        message = listOfNotNull(source.chapterTitle, source.quoteText.takeIf { it.isNotBlank() })
                            .joinToString("：")
                            .ifBlank { source.anchor.ifBlank { "来源 ${source.id}" } },
                        isError = false,
                    )
                }
            }

            val remoteRelations = relations.takeIf { it.isNotEmpty() }
            if (remoteRelations != null) {
                Text("后端关系详情", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                remoteRelations.take(8).forEach { relation ->
                    RemoteRelationRow(relation = relation, currentNodeId = node.id, onNodeSelected = onNodeSelected)
                }
            }

            if (incidentEdges.isEmpty()) {
                Text(
                    text = "当前节点暂无直接关系。",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                Text("直接关系", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                incidentEdges.forEach { edge ->
                    val otherNodeId = if (edge.sourceNodeId == node.id) edge.targetNodeId else edge.sourceNodeId
                    val otherNode = nodeById[otherNodeId]
                    RelationRow(
                        edge = edge,
                        otherNode = otherNode,
                        outgoing = edge.sourceNodeId == node.id,
                        onClick = { if (otherNode != null) onNodeSelected(otherNode.id) },
                    )
                }
            }
        }
    }
}

@Composable
private fun RelationRow(
    edge: GraphEdgeResponse,
    otherNode: KnowledgeUnitResponse?,
    outgoing: Boolean,
    onClick: () -> Unit,
) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(enabled = otherNode != null, onClick = onClick),
        color = MaterialTheme.colorScheme.surfaceContainer,
        shape = MaterialTheme.shapes.medium,
    ) {
        Row(
            modifier = Modifier.padding(12.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = if (outgoing) "→" else "←",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.primary,
            )
            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                MarkdownText(
                    markdown = otherNode?.canonicalName ?: "未知节点",
                    textSizeSp = 14f,
                    color = MaterialTheme.colorScheme.onSurface,
                    linkColor = MaterialTheme.colorScheme.primary,
                    maxLines = 1,
                )
                Text(
                    text = "${edgeTypeLabel(edge.edgeType)} · 权重 ${formatDecimal(edge.weight)} · 置信度 ${formatPercent(edge.confidence)}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun RemoteRelationRow(
    relation: KnowledgeRelationResponse,
    currentNodeId: Int,
    onNodeSelected: (Int) -> Unit,
) {
    val otherId = if (relation.sourceNodeId == currentNodeId) relation.targetNodeId else relation.sourceNodeId
    val otherName = if (relation.sourceNodeId == currentNodeId) relation.targetNodeName else relation.sourceNodeName
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(enabled = otherId > 0) { onNodeSelected(otherId) },
        color = MaterialTheme.colorScheme.surfaceContainer,
        shape = MaterialTheme.shapes.medium,
    ) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(otherName.ifBlank { "关联知识点 $otherId" }, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
            Text(
                "${edgeTypeLabel(relation.edgeType)} · 置信度 ${formatPercent(relation.confidence)}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            relation.description.takeIf { it.isNotBlank() }?.let {
                MarkdownText(markdown = it, textSizeSp = 13f, maxLines = 4)
            }
        }
    }
}

@Composable
private fun GraphLoadingCard() {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surfaceContainer,
        shape = MaterialTheme.shapes.large,
    ) {
        Row(
            modifier = Modifier.padding(20.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
            Text("正在加载知识图谱...")
        }
    }
}

@Composable
private fun EmptyGraphCard(
    onOpenDocs: () -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surfaceContainer,
        shape = MaterialTheme.shapes.large,
    ) {
        Column(
            modifier = Modifier.padding(22.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Icon(Icons.Outlined.Insights, contentDescription = null, modifier = Modifier.size(42.dp))
            Text("暂无知识图谱", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(
                "完成知识文档构建后，系统会同步抽取知识点和关系。这里会按当前学科动态展示图谱。",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Button(onClick = onOpenDocs) {
                Text("查看知识文档")
            }
        }
    }
}

@Composable
private fun GraphMessageCard(
    message: String,
    isError: Boolean,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = if (isError) MaterialTheme.colorScheme.errorContainer else MaterialTheme.colorScheme.primaryContainer,
        shape = MaterialTheme.shapes.medium,
    ) {
        Text(
            text = message,
            modifier = Modifier.padding(12.dp),
            style = MaterialTheme.typography.bodySmall,
            color = if (isError) MaterialTheme.colorScheme.onErrorContainer else MaterialTheme.colorScheme.onPrimaryContainer,
        )
    }
}

private data class NodePosition(
    val x: Float,
    val y: Float,
)

private data class NodeTone(
    val background: Color,
    val content: Color,
)

private fun FullGraphResponse.visibleGraphNodes(selectedNodeId: Int?): List<KnowledgeUnitResponse> {
    val degree = edges
        .flatMap { listOf(it.sourceNodeId, it.targetNodeId) }
        .groupingBy { it }
        .eachCount()
    val selected = selectedNodeId?.let { id -> nodes.firstOrNull { it.id == id } }
    val ranked = nodes
        .filter { it.id != selectedNodeId }
        .sortedWith(
            compareByDescending<KnowledgeUnitResponse> { degree[it.id] ?: 0 }
                .thenByDescending { it.confidence }
                .thenBy { it.canonicalName },
        )
        .take(if (selected == null) 24 else 23)
    return if (selected == null) ranked else listOf(selected) + ranked
}

private fun calculateGraphPositions(nodes: List<KnowledgeUnitResponse>): Map<Int, NodePosition> {
    if (nodes.isEmpty()) return emptyMap()
    if (nodes.size == 1) return mapOf(nodes.first().id to NodePosition(0.5f, 0.5f))

    val center = nodes.first()
    val outerNodes = nodes.drop(1)
    val positions = mutableMapOf(center.id to NodePosition(0.5f, 0.5f))
    outerNodes.forEachIndexed { index, node ->
        val angle = (2.0 * PI * index / outerNodes.size) - (PI / 2.0)
        positions[node.id] = NodePosition(
            x = (0.5 + 0.38 * cos(angle)).toFloat(),
            y = (0.5 + 0.36 * sin(angle)).toFloat(),
        )
    }
    return positions
}

private fun FullGraphResponse.degreeOf(nodeId: Int): Int {
    return edges.count { it.sourceNodeId == nodeId || it.targetNodeId == nodeId }
}

private fun nodeTypeLabel(type: String): String {
    return when (type.lowercase()) {
        "concept" -> "概念"
        "method" -> "方法"
        "example" -> "例题"
        "principle" -> "原理"
        "procedure" -> "步骤"
        "practice_assessment" -> "练习"
        "fact" -> "事实"
        else -> type.ifBlank { "知识点" }
    }
}

private fun nodeTypeInitial(type: String): String {
    return nodeTypeLabel(type).take(1).ifBlank { "知" }
}

private fun nodeTypeTone(type: String): NodeTone {
    return when (type.lowercase()) {
        "concept" -> NodeTone(background = Color(0xFFEFF6FF), content = Color(0xFF1D4ED8))
        "method" -> NodeTone(background = Color(0xFFECFDF5), content = Color(0xFF047857))
        "example" -> NodeTone(background = Color(0xFFFFF7ED), content = Color(0xFFC2410C))
        "principle" -> NodeTone(background = Color(0xFFF5F3FF), content = Color(0xFF6D28D9))
        "procedure" -> NodeTone(background = Color(0xFFF0FDFA), content = Color(0xFF0F766E))
        "practice_assessment" -> NodeTone(background = Color(0xFFFFF1F2), content = Color(0xFFBE123C))
        else -> NodeTone(background = Color(0xFFF1F5F9), content = Color(0xFF334155))
    }
}

private fun edgeTypeLabel(type: String): String {
    return when (type.lowercase()) {
        "prerequisite", "requires" -> "先修"
        "derives", "derivation" -> "推导"
        "applies", "application" -> "应用"
        "similar", "compare" -> "对比"
        "example_of" -> "例证"
        "part_of" -> "组成"
        else -> type.ifBlank { "关联" }
    }
}

private fun formatPercent(value: Double): String {
    return "${(value.coerceIn(0.0, 1.0) * 100).toInt()}%"
}

private fun formatDecimal(value: Double): String {
    return "%.2f".format(value)
}
