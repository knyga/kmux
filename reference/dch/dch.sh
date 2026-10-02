# dch — enter a folder's devcontainer: build/start it if needed, then open a shell in it.
# Host-side. Sourced from ~/.bashrc / ~/.zshrc. Needs docker and the devcontainer CLI
# (npm install -g @devcontainers/cli).
#   dch            # devcontainer of $PWD
#   dch <folder>   # devcontainer of <folder>
dch() {
    local folder="${1:-$PWD}"
    if [[ ! -d "$folder/.devcontainer" ]]; then
      echo "no .devcontainer in $folder" >&2
      return 1
    fi
    devcontainer up --workspace-folder "$folder" >/dev/null || return
    devcontainer exec --workspace-folder "$folder" "${DCH_SHELL:-zsh}"
}
