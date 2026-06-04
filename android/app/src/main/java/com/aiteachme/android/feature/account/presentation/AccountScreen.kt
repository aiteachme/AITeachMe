package com.aiteachme.android.feature.account.presentation

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.automirrored.outlined.Login
import androidx.compose.material.icons.automirrored.outlined.Logout
import androidx.compose.material.icons.outlined.AccountCircle
import androidx.compose.material.icons.outlined.Mail
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.aiteachme.android.core.network.dto.RuntimeUser

@Composable
fun AccountScreen(
    contentPadding: PaddingValues,
    onBack: () -> Unit,
    viewModel: AccountViewModel = viewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()

    LaunchedEffect(Unit) {
        viewModel.loadSession()
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(contentPadding)
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp, vertical = 18.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            OutlinedButton(onClick = onBack) {
                Icon(
                    imageVector = Icons.AutoMirrored.Outlined.ArrowBack,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp),
                )
            }
            Text(
                text = "我的",
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.SemiBold,
            )
        }

        AccountStatusCard(
            uiState = uiState,
            onRefresh = viewModel::loadSession,
            onLogout = viewModel::logout,
        )

        when {
            uiState.isLoading -> LoadingAccount()
            uiState.authEnabled == false -> AuthDisabledCard()
            uiState.user?.isAuthenticated == true -> LoggedInCard(user = uiState.user)
            else -> AuthForm(
                uiState = uiState,
                onModeChange = viewModel::setMode,
                onEmailChange = viewModel::updateEmail,
                onPasswordChange = viewModel::updatePassword,
                onVerificationCodeChange = viewModel::updateVerificationCode,
                onSendCode = viewModel::sendVerificationCode,
                onSubmit = viewModel::submit,
            )
        }
    }
}

@Composable
private fun AccountStatusCard(
    uiState: AccountUiState,
    onRefresh: () -> Unit,
    onLogout: () -> Unit,
) {
    val user = uiState.user
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surfaceContainer,
        shape = MaterialTheme.shapes.large,
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Icon(
                    imageVector = Icons.Outlined.AccountCircle,
                    contentDescription = null,
                    modifier = Modifier.size(40.dp),
                    tint = MaterialTheme.colorScheme.primary,
                )
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = displayName(user),
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Text(
                        text = accountSubtitle(uiState),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }

            uiState.errorMessage?.let {
                Text(
                    text = it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }
            uiState.infoMessage?.let {
                Text(
                    text = it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.primary,
                )
            }

            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                FilledTonalButton(
                    onClick = onRefresh,
                    enabled = !uiState.isLoading && !uiState.isSubmitting,
                ) {
                    if (uiState.isLoading) {
                        CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                        Spacer(modifier = Modifier.width(8.dp))
                    }
                    Text("刷新状态")
                }
                if (user?.isAuthenticated == true) {
                    OutlinedButton(
                        onClick = onLogout,
                        enabled = !uiState.isSubmitting,
                    ) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Outlined.Logout,
                            contentDescription = null,
                            modifier = Modifier.size(18.dp),
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text("退出")
                    }
                }
            }
        }
    }
}

@Composable
private fun LoadingAccount() {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        CircularProgressIndicator(modifier = Modifier.size(24.dp), strokeWidth = 2.dp)
        Spacer(modifier = Modifier.width(12.dp))
        Text("正在读取账号状态")
    }
}

@Composable
private fun AuthDisabledCard() {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surfaceContainer,
        shape = MaterialTheme.shapes.large,
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                text = "当前后端未启用账号登录",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = "本地模式会使用当前设备的临时身份访问学习空间数据。等后端开启鉴权后，这里会显示邮箱登录和注册表单。",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun LoggedInCard(user: RuntimeUser?) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surfaceContainer,
        shape = MaterialTheme.shapes.large,
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                text = "已登录",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = user?.email ?: "账号信息不可用",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun AuthForm(
    uiState: AccountUiState,
    onModeChange: (AuthMode) -> Unit,
    onEmailChange: (String) -> Unit,
    onPasswordChange: (String) -> Unit,
    onVerificationCodeChange: (String) -> Unit,
    onSendCode: () -> Unit,
    onSubmit: () -> Unit,
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
            SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
                AuthMode.entries.forEachIndexed { index, mode ->
                    SegmentedButton(
                        selected = uiState.mode == mode,
                        onClick = { onModeChange(mode) },
                        shape = SegmentedButtonDefaults.itemShape(
                            index = index,
                            count = AuthMode.entries.size,
                        ),
                    ) {
                        Text(if (mode == AuthMode.Login) "登录" else "注册")
                    }
                }
            }

            OutlinedTextField(
                value = uiState.email,
                onValueChange = onEmailChange,
                modifier = Modifier.fillMaxWidth(),
                label = { Text("邮箱") },
                leadingIcon = {
                    Icon(imageVector = Icons.Outlined.Mail, contentDescription = null)
                },
                singleLine = true,
                keyboardOptions = KeyboardOptions(
                    keyboardType = KeyboardType.Email,
                    imeAction = ImeAction.Next,
                ),
            )

            OutlinedTextField(
                value = uiState.password,
                onValueChange = onPasswordChange,
                modifier = Modifier.fillMaxWidth(),
                label = { Text("密码") },
                singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(
                    keyboardType = KeyboardType.Password,
                    imeAction = if (uiState.mode == AuthMode.Login) ImeAction.Done else ImeAction.Next,
                ),
            )

            if (uiState.mode == AuthMode.Register) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    OutlinedTextField(
                        value = uiState.verificationCode,
                        onValueChange = onVerificationCodeChange,
                        modifier = Modifier.weight(1f),
                        label = { Text("验证码") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(
                            keyboardType = KeyboardType.Text,
                            imeAction = ImeAction.Done,
                        ),
                    )
                    OutlinedButton(
                        onClick = onSendCode,
                        enabled = !uiState.isSendingCode && !uiState.isSubmitting,
                    ) {
                        Text(if (uiState.isSendingCode) "发送中" else "发码")
                    }
                }
            }

            Button(
                onClick = onSubmit,
                enabled = !uiState.isSubmitting && !uiState.isSendingCode,
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (uiState.isSubmitting) {
                    CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                    Spacer(modifier = Modifier.width(8.dp))
                } else {
                    Icon(
                        imageVector = Icons.AutoMirrored.Outlined.Login,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp),
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                }
                Text(if (uiState.mode == AuthMode.Login) "登录" else "注册")
            }
        }
    }
}

private fun displayName(user: RuntimeUser?): String {
    if (user?.isAuthenticated == true) {
        return user.email?.substringBefore("@")?.ifBlank { "用户" } ?: "用户"
    }
    return "游客"
}

private fun accountSubtitle(uiState: AccountUiState): String {
    val user = uiState.user
    return when {
        uiState.authEnabled == false -> "本地模式，无需登录"
        user?.isAuthenticated == true -> user.email ?: "已登录账号"
        user?.userId != null -> "访客身份 ${user.userId.takeLast(6)}"
        else -> "读取账号状态后可登录"
    }
}
