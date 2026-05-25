import "@testing-library/jest-dom/vitest";

if (typeof window !== "undefined") {
	window.URL.createObjectURL ??= () => "blob:test";
	window.URL.revokeObjectURL ??= () => undefined;

	const noop = () => undefined;
	Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
		value: () => ({
			clearRect: noop,
			fillRect: noop,
			getImageData: () => ({ data: [] }),
			putImageData: noop,
			createImageData: () => [],
			setTransform: noop,
			drawImage: noop,
			save: noop,
			fillText: noop,
			restore: noop,
			beginPath: noop,
			moveTo: noop,
			lineTo: noop,
			closePath: noop,
			stroke: noop,
			translate: noop,
			scale: noop,
			rotate: noop,
			arc: noop,
			fill: noop,
			measureText: () => ({ width: 0 }),
			transform: noop,
			rect: noop,
			clip: noop,
		}),
		writable: true,
	});

	if (!("ResizeObserver" in globalThis)) {
		class ResizeObserverMock {
			observe() {
				return undefined;
			}

			unobserve() {
				return undefined;
			}

			disconnect() {
				return undefined;
			}
		}

		Reflect.set(globalThis, "ResizeObserver", ResizeObserverMock);
	}
}