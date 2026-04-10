declare module "d3-cloud" {
  export interface CloudWord {
    text?: string;
    size?: number;
    x?: number;
    y?: number;
    rotate?: number;
  }

  export interface CloudLayout<T extends CloudWord> {
    size(value: [number, number]): CloudLayout<T>;
    words(value: T[]): CloudLayout<T>;
    padding(value: number): CloudLayout<T>;
    rotate(value: (word: T, index: number) => number): CloudLayout<T>;
    font(value: string): CloudLayout<T>;
    fontSize(value: (word: T) => number): CloudLayout<T>;
    spiral(value: string): CloudLayout<T>;
    on(event: "end", listener: (words: T[]) => void): CloudLayout<T>;
    start(): void;
    stop(): void;
  }

  export default function cloud<T extends CloudWord>(): CloudLayout<T>;
}
