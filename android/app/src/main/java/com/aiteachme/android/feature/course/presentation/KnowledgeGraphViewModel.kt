package com.aiteachme.android.feature.course.presentation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aiteachme.android.core.di.AppServices
import com.aiteachme.android.core.network.dto.FullGraphResponse
import com.aiteachme.android.core.network.dto.KnowledgeOverviewResponse
import com.aiteachme.android.core.network.dto.KnowledgeRelationResponse
import com.aiteachme.android.core.network.dto.KnowledgeUnitDetailResponse
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class KnowledgeGraphUiState(
    val graph: FullGraphResponse = FullGraphResponse(),
    val overview: KnowledgeOverviewResponse? = null,
    val selectedNodeId: Int? = null,
    val selectedDetail: KnowledgeUnitDetailResponse? = null,
    val selectedRelations: List<KnowledgeRelationResponse> = emptyList(),
    val isLoading: Boolean = false,
    val isLoadingDetail: Boolean = false,
    val isBuildingGraph: Boolean = false,
    val errorMessage: String? = null,
    val infoMessage: String? = null,
)

class KnowledgeGraphViewModel : ViewModel() {
    private val knowledgeRepository = AppServices.knowledgeRepository

    private val _uiState = MutableStateFlow(KnowledgeGraphUiState())
    val uiState: StateFlow<KnowledgeGraphUiState> = _uiState.asStateFlow()

    fun load(courseId: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, errorMessage = null) }
            runCatching {
                knowledgeRepository.getKnowledgeOverview(courseId)
            }.onSuccess { overview ->
                val graph = overview.graph ?: knowledgeRepository.getKnowledgeGraph(courseId)
                _uiState.update {
                    it.copy(
                        graph = graph,
                        overview = overview,
                        selectedNodeId = it.selectedNodeId?.takeIf { id -> graph.nodes.any { node -> node.id == id } },
                        isLoading = false,
                        errorMessage = null,
                    )
                }
            }.onFailure { throwable ->
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        errorMessage = throwable.message ?: throwable::class.java.simpleName,
                    )
                }
            }
        }
    }

    fun selectNode(nodeId: Int?) {
        _uiState.update { it.copy(selectedNodeId = nodeId) }
    }

    fun selectNode(courseId: String, nodeId: Int?) {
        _uiState.update {
            it.copy(
                selectedNodeId = nodeId,
                selectedDetail = null,
                selectedRelations = emptyList(),
                errorMessage = null,
            )
        }
        if (nodeId == null || courseId.isBlank()) return
        viewModelScope.launch {
            _uiState.update { it.copy(isLoadingDetail = true) }
            runCatching {
                val detail = knowledgeRepository.getKnowledgeUnitDetail(courseId, nodeId)
                val relations = knowledgeRepository.getKnowledgeUnitRelations(courseId, nodeId)
                detail to relations
            }.onSuccess { (detail, relations) ->
                _uiState.update {
                    it.copy(
                        selectedDetail = detail,
                        selectedRelations = relations,
                        isLoadingDetail = false,
                    )
                }
            }.onFailure { throwable ->
                _uiState.update {
                    it.copy(
                        isLoadingDetail = false,
                        errorMessage = throwable.message ?: throwable::class.java.simpleName,
                    )
                }
            }
        }
    }

    fun startGraphBuild(courseId: String) {
        if (courseId.isBlank() || _uiState.value.isBuildingGraph) return
        viewModelScope.launch {
            _uiState.update { it.copy(isBuildingGraph = true, errorMessage = null, infoMessage = null) }
            runCatching {
                knowledgeRepository.startKnowledgeGraphBuild(courseId)
            }.onSuccess {
                _uiState.update {
                    it.copy(
                        isBuildingGraph = false,
                        infoMessage = "知识图谱构建已启动",
                    )
                }
                load(courseId)
            }.onFailure { throwable ->
                _uiState.update {
                    it.copy(
                        isBuildingGraph = false,
                        errorMessage = throwable.message ?: throwable::class.java.simpleName,
                    )
                }
            }
        }
    }
}
