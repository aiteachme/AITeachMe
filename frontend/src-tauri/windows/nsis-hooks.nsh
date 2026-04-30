!macro NSIS_HOOK_PREINSTALL
  Delete "$INSTDIR\aiteachme-backend.exe"
  Delete "$INSTDIR\backend.log"
  Delete "$INSTDIR\resources\backend\aiteachme-backend.exe"
!macroend

!macro NSIS_HOOK_POSTINSTALL
  SetFileAttributes "$INSTDIR\uninstall.exe" HIDDEN
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  SetFileAttributes "$INSTDIR\uninstall.exe" NORMAL
!macroend
