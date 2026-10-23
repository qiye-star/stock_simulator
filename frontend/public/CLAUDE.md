# public（静态资源，给 agent）

- 此目录内容原样拷贝到构建产物根目录，由 Vite 不做处理。
- 引用方式用根路径：`/images/cover.jpg`（不要写 `public/...`，也不要 import）。
- 不放代码或需要打包的资源；需要打包的资源放 `src/`。
