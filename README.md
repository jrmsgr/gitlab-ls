# Gitlab-ls

## Setup
- Clone this repo
- Create a gitlab config file named `config.cfg` in the repo directory. Gitlba config files are explained [on their website](https://python-gitlab.readthedocs.io/en/stable/cli-usage.html#configuration-file-format)
- Install the requirements:
```bash
pip3 install -r requirements.txt
```
- Configure your editor to start gitlab-ls. Example neovim config:
```lua
local cmp = require("cmp")
vim.api.nvim_create_autocmd("FileType", {
    pattern = "text",
    callback = function()
        local client = vim.lsp.start_client({
            name = "gitlab-ls",
            cmd = { "path/to/gitlab-ls.py" },
            init_options = {
                -- Your list of project paths you want to load
                -- For example if a project URL is https://my.gitlab.repo/project/path
                -- and that the site url specified in config.cfg is 'https://my.gitlab.repo'
                -- put 'project/path' in this list
                projects = { "project/path" },
            },
        })
        if not client then
            vim.notify("Failed to start gitlab-ls", vim.log.levels.ERROR, {})
        end
        vim.api.nvim_set_hl(0, "CmpItemKindText", { link = "DiagnosticError" })
        vim.api.nvim_set_hl(0, "CmpItemKindMethod", { link = "DiagnosticOk" })
        vim.lsp.buf_attach_client(0, client)
        cmp.setup.buffer({
            formatting = {
                format = function(entry, vim_item)
                    local prefix = (vim_item.kind == "Method") and "" or ""
                    vim_item.kind = string.format("%s %s", prefix, vim_item.menu) -- This concatenates the icons with the name of the item kind
                    vim_item.menu = ""
                    return vim_item
                end,
            },
        })
    end,
})
```
