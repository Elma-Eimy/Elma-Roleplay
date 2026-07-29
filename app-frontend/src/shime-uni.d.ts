export {}

declare module "vue" {
  type Hooks = App.AppInstance & Page.PageInstance;
  interface ComponentCustomOptions extends Hooks {}

  interface ComponentCustomProperties {
    /** uni-app RenderJS module exposed to chat.vue templates. */
    stream: {
      onStreamRequestChange: (...args: unknown[]) => void;
    };
  }
}
