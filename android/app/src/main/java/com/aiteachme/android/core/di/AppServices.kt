package com.aiteachme.android.core.di

import android.content.Context
import com.aiteachme.android.core.data.repository.AuthRepository
import com.aiteachme.android.core.data.repository.ChatRepository
import com.aiteachme.android.core.data.repository.CourseRepository
import com.aiteachme.android.core.data.repository.DailyWallpaperRepository
import com.aiteachme.android.core.data.repository.ExamRepository
import com.aiteachme.android.core.data.repository.FileRepository
import com.aiteachme.android.core.data.repository.KnowledgeRepository
import com.aiteachme.android.core.data.repository.ProfileRepository
import com.aiteachme.android.core.data.repository.SystemRepository
import com.aiteachme.android.core.network.AiTeachMeApi
import com.aiteachme.android.core.network.BackendApiClient
import com.aiteachme.android.core.network.NetworkModule
import com.aiteachme.android.core.session.SessionStore
import com.aiteachme.android.core.state.CourseContextStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

object AppServices {
    lateinit var sessionStore: SessionStore
        private set
    lateinit var api: AiTeachMeApi
        private set
    lateinit var backendApiClient: BackendApiClient
        private set
    lateinit var authRepository: AuthRepository
        private set
    lateinit var courseRepository: CourseRepository
        private set
    lateinit var chatRepository: ChatRepository
        private set
    lateinit var fileRepository: FileRepository
        private set
    lateinit var knowledgeRepository: KnowledgeRepository
        private set
    lateinit var examRepository: ExamRepository
        private set
    lateinit var profileRepository: ProfileRepository
        private set
    lateinit var systemRepository: SystemRepository
        private set
    lateinit var dailyWallpaperRepository: DailyWallpaperRepository
        private set
    lateinit var courseContextStore: CourseContextStore
        private set

    private var initialized = false
    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    fun init(context: Context) {
        if (initialized) {
            return
        }
        sessionStore = SessionStore(context.applicationContext)
        courseContextStore = CourseContextStore(context.applicationContext)
        api = NetworkModule.createApi(sessionStore = sessionStore)
        backendApiClient = BackendApiClient(sessionStore = sessionStore)
        authRepository = AuthRepository(api = api, sessionStore = sessionStore)
        courseRepository = CourseRepository(api = api)
        chatRepository = ChatRepository(api = api, sessionStore = sessionStore)
        fileRepository = FileRepository(api = api, context = context.applicationContext)
        knowledgeRepository = KnowledgeRepository(api = api, sessionStore = sessionStore)
        examRepository = ExamRepository(api = api)
        profileRepository = ProfileRepository(api = api)
        systemRepository = SystemRepository(api = api)
        dailyWallpaperRepository = DailyWallpaperRepository(context = context.applicationContext)
        dailyWallpaperRepository.loadWallpaperForDisplay()
        appScope.launch {
            dailyWallpaperRepository.prepareNextWallpaper()
        }
        initialized = true
    }
}
