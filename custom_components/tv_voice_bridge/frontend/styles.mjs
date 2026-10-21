export const baseStyles = `
        :host { display: block; }
        ha-card { padding: 10px 14px; border: none; box-shadow: none; }
        button { display: flex; align-items: center; justify-content: center;
          gap: 10px; width: 100%; min-height: 48px; padding: 10px;
          border: 1px solid var(--divider-color); border-radius: 24px;
          color: var(--primary-text-color); background: var(--secondary-background-color);
          font: inherit; font-weight: 600; cursor: pointer;
          touch-action: none; user-select: none; -webkit-user-select: none;
          -webkit-touch-callout: none; }
        button:focus-visible { outline: 3px solid var(--primary-color); }
        button:disabled { cursor: wait; opacity: .7; }
        button.recording { background: var(--error-color, #db4437); color: white; }
        ha-icon { --mdc-icon-size: 26px; }
        p { margin: 8px 2px 0; color: var(--secondary-text-color); font-size: 12px;
          line-height: 1.4; text-align: center; min-height: 17px; }
        p.error { color: var(--error-color); }
        .meter { height: 4px; margin: 8px 12px 0; border-radius: 2px;
          background: var(--divider-color); overflow: hidden; }
        .meter[hidden] { display: none; }
        .level { height: 100%; width: 0; background: var(--primary-color); transition: width .08s; }
`;
