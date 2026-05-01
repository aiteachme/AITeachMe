!macro NSIS_HOOK_PREINSTALL
  SetOverwrite on
  nsExec::ExecToLog 'taskkill /F /T /IM aiteachme-local.exe'
  nsExec::ExecToLog 'taskkill /F /T /IM aiteachme-backend.bin'
  RMDir /r "$INSTDIR\backend"
  Delete "$INSTDIR\aiteachme-backend.exe"
  Delete "$INSTDIR\aiteachme-backend.bin"
  Delete "$INSTDIR\backend.log"
  Delete "$INSTDIR\resources\backend\aiteachme-backend.exe"
  Delete "$INSTDIR\resources\backend\aiteachme-backend.bin"
  RMDir /r "$INSTDIR\resources\backend"
!macroend

!macro NSIS_HOOK_POSTINSTALL
  SetFileAttributes "$INSTDIR\uninstall.exe" HIDDEN
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  SetFileAttributes "$INSTDIR\uninstall.exe" NORMAL
!macroend
