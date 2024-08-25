# Gitlab-ls

## Setup
- Clone this repo
- Configure neovim (we're using [lazy.nvim](https://github.com/folke/lazy.nvim) to manage plugins here):
```lua
require("lazy").setup({
  {
    "jrmsgr/gitlab-ls",
    dependencies = { "neovim/nvim-lspconfig", "hrsh7th/nvim-cmp" },
    opts = { -- Plugin's config
      -- Max length of a completion item in the popup window
      -- '...' is appended to the item if it is truncated
      max_txt_len = 20,
      -- Icon symbol used in the completion popup for open issues/merge requests
      open_icon = "",
      -- Icon symbol used in the completion popup for closed issues/merge requests
      closed_icon = "",
      -- If true, changes the highlight of the completion items in the completion window to
      -- to 'DiagnosticError' (resp. 'DiagnosticOk') if the item is closed (resp. open)
      override_cmp_items_highlight = false,

      -- Server configuration. This config is passed directly to nvim-lspconfig (https://github.com/neovim/nvim-lspconfig).
      -- Therefore it supports all the options specified in its documentation.
      server_config = {
        name = "gitlab-ls",
        filetypes = { "text" },
        -- /!\ MANDATORY INIT OPTIONS
        init_options = {
          -- URL of the gitlab instance hosting the projects
          url = "https://my.gitlab.repo",
          -- Private token to access the gitlab instance
          -- For better safety, use a read-only token
          private_token = "<MY_PRIVATE_TOKEN>",
          -- Your list of project paths you want to load
          -- For example if a project URL is https://my.gitlab.repo/project/path
          -- put 'project/path' in this list
          projects = { "project/path" },
        },
      },
    },
  },
})
```
