import { useState } from 'react';
import type { WidgetConfig } from '@ai-cs/shared/types';
import { WidgetLauncher } from './WidgetLauncher';
import { WidgetWindow } from './WidgetWindow';

interface WidgetComponentProps {
  config: WidgetConfig;
  suggestions?: string[];
}

export function WidgetComponent({ config, suggestions }: WidgetComponentProps) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <>
      {!isOpen && (
        <WidgetLauncher
          config={config}
          isOpen={isOpen}
          onClick={() => setIsOpen(!isOpen)}
        />
      )}
      {isOpen && (
        <WidgetWindow
          config={config}
          suggestions={suggestions}
          onClose={() => setIsOpen(false)}
        />
      )}
    </>
  );
}
