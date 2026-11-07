"""Keep measurement labels within each eye and separate them where possible."""


def place_labels(items, bounds):
    left, top, right, bottom = bounds
    occupied, result = [], []
    for x, y, width, height in items:
        width, height = min(width, right-left-12), min(height, bottom-top-12)
        candidates = [(x+10, y-height-6), (x-width-10, y-height-6),
                      (x+10, y+8), (x-width-10, y+8),
                      (x+10, y-height/2), (x-width-10, y-height/2),
                      (x-width/2, y-height-14), (x-width/2, y+14)]
        for rect in occupied:
            candidates.extend([(rect[0], rect[3]+8), (rect[0], rect[1]-height-8),
                               (rect[2]+8, rect[1]), (rect[0]-width-8, rect[1])])
        choices = []
        for index, (tx, ty) in enumerate(candidates):
            cx = max(left+6, min(right-width-6, tx))
            cy = max(top+6, min(bottom-height-6, ty))
            rect = (cx, cy, cx+width, cy+height)
            overlap = sum(max(0, min(rect[2], r[2])-max(rect[0], r[0])+5)
                          * max(0, min(rect[3], r[3])-max(rect[1], r[1])+5) for r in occupied)
            covered = sum(rect[0]-4 <= px <= rect[2]+4 and rect[1]-4 <= py <= rect[3]+4
                          for px, py, *_ in items)
            choices.append((overlap*1000+covered*10000+abs(cx-tx)+abs(cy-ty)+index, rect, index))
        _, rect, index = min(choices)
        occupied.append(rect)
        result.append((rect, index >= 4))
    return result
