local function get_gitlab_ls_exec_path()
  local script_path = debug.getinfo(1, "S").source:sub(2)
  local plugin_dir = vim.fs.root(script_path, ".git")
  return plugin_dir .. "/gitlab-ls.sh"
end

--@type vim.lsp.Config
return {
  cmd = {get_gitlab_ls_exec_path()},
  on_attach = function (client, bufnr)
    vim.diagnostic.config({
        signs = {
            text = {
                -- "opened" state
                [vim.diagnostic.severity.WARN] = '',
                -- "merged" state
                [vim.diagnostic.severity.INFO] = '',
                -- "closed" state
                [vim.diagnostic.severity.ERROR] = '',
            },
          }
    })
  end
}
