; v1.0.0/v1.0.1 updater exits before their sidecar shutdown handler runs.
; New clients stop the engine gracefully before installation; this installer
; hook is the bridge fallback that prevents a legacy sidecar from locking files.
!macro NSIS_HOOK_PREINSTALL
  nsExec::ExecToStack '"$SYSDIR\taskkill.exe" /F /T /IM forming_grinder_cad_sidecar.exe'
  Pop $0
  Pop $1
  Sleep 500
!macroend
