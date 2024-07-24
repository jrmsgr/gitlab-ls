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
cmp.event:on("confirm_done", function(evt) -- Replace title with url
    if evt.entry.source.name == "nvim_lsp" then
        if evt.entry.source.source.client.name == "gitlab-ls" then
            local line = evt.entry.source_insert_range.start.line
            local start_col = evt.entry.source_insert_range.start.character - 1
            local end_col = start_col + string.len(evt.entry.completion_item.label)
            local text = string.match(evt.entry.completion_item.label, "^[^ ]+")
            local prefix = string.sub(text, 1, 1)
            vim.api.nvim_buf_set_text(0, line, start_col, line, end_col, {
                evt.entry.source.source.client.config.init_options.url
                    .. "/"
                    .. evt.entry.completion_item.labelDetails.detail
                    .. "/-/"
                .. ((prefix == "!") and "merge_requests/" or "issues/")
                    .. string.sub(text, 2, -1),
            })
        end
    end
end)
vim.api.nvim_create_autocmd("FileType", {
    pattern = "text",
    callback = function()
        local client = vim.lsp.start_client({
            name = "gitlab-ls",
            cmd = { "path/to/gitlab-ls.py" },
            init_options = {
                -- URL of the gitlab instance hosting the projects
                url = "https://my.gitlab.repo",
                -- Private token to access the gitlab instance
                -- For better safety, use a read-only token
                private_token= "<MY_PRIVATE_TOKEN>",
                -- Your list of project paths you want to load
                -- For example if a project URL is https://my.gitlab.repo/project/path
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
