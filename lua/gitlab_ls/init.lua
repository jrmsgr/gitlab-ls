local cmp = require("cmp")
local cmp_config = require("cmp.config")
local lspconfigs = require("lspconfig.configs")

local gitlab_ls = {}

local default_opts = {
  max_txt_len = 20,
  opened_icon = "",
  closed_icon = "",
  override_cmp_items_highlight = false,
  server_config = {
    name = "gitlab-ls",
    filetypes = { "text" },
    single_file_support = true,
  },
}

local function get_gitlab_ls_exec_path()
  local script_path = debug.getinfo(1, "S").source:sub(2)
  local plugin_dir = vim.fs.root(script_path, ".git")
  return plugin_dir .. "/gitlab-ls.sh"
end

function gitlab_ls.setup(opts)
  opts = opts or {}
  opts = vim.tbl_deep_extend("force", default_opts, opts)

  if opts.server_config.on_attach then
    error("Setting 'on_attach' in the server configuration is not allowed", vim.log.log_level.error)
  end

  if not opts.server_config.cmd then
    opts.server_config.cmd = { get_gitlab_ls_exec_path() }
  end

  opts.server_config.on_attach = function(client, bufnr)
    if opts.override_cmp_items_highlight then
      vim.api.nvim_set_hl(0, "CmpItemKindText", { link = "DiagnosticError" })
      vim.api.nvim_set_hl(0, "CmpItemKindMethod", { link = "DiagnosticOk" })
    end

    local function is_project(name)
      for _, project in ipairs(opts.server_config.init_options.projects) do
        if project == name then
          return true
        end
      end
      return false
    end

    cmp_config.set_buffer({
      formatting = {
        format = function(_, vim_item)
          if vim_item.menu and is_project(vim_item.menu) then
            local prefix = (vim_item.kind == "Method") and opts.opened_icon or opts.closed_icon
            if string.len(vim_item.word) > opts.max_txt_len then
              vim_item.abbr = string.sub(vim_item.word, 1, opts.max_txt_len) .. "..."
            end
            vim_item.kind = string.format("%s %s", prefix, vim_item.menu) -- This concatenates the icons with the name of the item kind
            vim_item.menu = ""
          end
          return vim_item
        end,
      },
    }, bufnr)
  end

  lspconfigs[opts.server_config.name] = { default_config = default_opts.server_config }
  lspconfigs[opts.server_config.name].setup(opts.server_config)

  cmp.event:on("confirm_done", function(evt)
    if evt.entry.source.name == "nvim_lsp" then
      if evt.entry.source.source.client.name == opts.server_config.name then
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
end

return gitlab_ls
