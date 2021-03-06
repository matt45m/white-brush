import numpy as np
import cv2

from white_brush.colors.color_balance import balance_color
from white_brush.colors.morphology import dilate, erode

from white_brush.colors.conversion import rgb_to_hsv, rgb_to_gray
from white_brush.colors.utils import _color_sample, _generate_bitmask, \
    _pack_rgb_values, _unpack_rgb_values


def hsv_distance_threshold(img: np.ndarray, bg_colors=None,
                           v_thresh=70, s_thresh=80) -> np.ndarray:
    """
    Calculate a foreground mask based on HSV distance.

    Decide which pixels constitute the foreground by calculating the
    difference between each pixel and each of the provided
    background colors in the HSV color space. Depending on the
    difference in the V and S channel mark each pixel as background or
    foreground.

    If a pixel is marked as background because it is close to only one
    of the specified bg colors, it will be in the background in the
    result also. (Results of each bg_color are combined with logical or)

    Args:
        img: The image for which to calculate a background / foreground
            mask
        bg_colors: The background colors to compare to. If only one
            of these colors are close enough to a pixel in the img to
            mark that pixel as belonging to background, it will be
            in the background in the resulting output
        v_thresh: Threshold for the V channel. If the difference between
            a color and the background color in the V channel is less
            than this, and also the same applies to s_thresh and the S
            channel, than the pixel is marked as belonging to the
            background.
        s_thresh: Threshold for the S channel.

    Returns:
        The calculated foreground mask. If an element in the mask is
        False, this means that the corresponding pixel is part of the
        background. If it is True, the pixel is part of the foreground.
    """
    # convert the hsv images to integers in order to avoid
    # uint8 overflows when calculating the difference later
    hsv_img = rgb_to_hsv(img).astype(np.int)

    if bg_colors is None:
        bg_colors = extract_background_colors(img)
    hsv_bgs = rgb_to_hsv(bg_colors).astype(np.int).reshape(*bg_colors.shape)

    def make_background_mask(hsv_img, hsv_bg):
        # the background is everything that has a difference less than
        # v_thresh in the v channel and less than s_thresh in the s channel
        background_mask = np.abs(hsv_img[:, :, 2] - hsv_bg[2]) <= v_thresh
        background_mask &= np.abs(hsv_img[:, :, 1] - hsv_bg[1]) <= s_thresh
        return background_mask

    print(hsv_bgs)
    background_masks = [make_background_mask(hsv_img, hsv_bg) for hsv_bg in
                        hsv_bgs]
    return ~(np.logical_or.reduce(background_masks))


def background_difference_image(img: np.ndarray,
                                kernel_size: int = 21,
                                blur_kernel_size: int = 7):
    """
    Calculate an Image which consits of only the difference between the
    given image and its background

    Args:
        img: The image to calculate the background diff image for
        kernel_size: Kernel size for the erosion that is used to
            create the background image
        blur_kernel_size: Parameter for the gaussian blur that will
            be performed on the background

    Returns:
        The background difference image
    """
    if img.ndim == 3:
        img = rgb_to_gray(img)
    # we want the background black, the foreground white
    # if that is not the case, flip black and white
    if np.median(img) > 80:
        img = 255 - img

    blurred = cv2.medianBlur(img, blur_kernel_size)

    background = erode(blurred, kernel_size)
    # calculate difference as integer, otherwise uint8 overflow will occurr
    diff = img.astype(np.int) - background.astype(np.int)
    diff = balance_color(diff, percentile=1, separate_channels=False)
    diff = dilate(erode(diff, 3), 3)
    return 255 - diff


def eroded_background_difference_threshold(img: np.ndarray,
                                           kernel_size: int = 21,
                                           blur_kernel_size: int = 7):
    gray_img = rgb_to_gray(img)
    # we want the background black, the foreground white
    # if that is not the case, flip black and white
    if np.median(gray_img) > 80:
        gray_img = 255 - gray_img

    blurred = cv2.medianBlur(gray_img, blur_kernel_size)

    background = erode(blurred, kernel_size)
    # calculate difference as integer, otherwise uint8 overflow will occurr
    diff = gray_img.astype(np.int) - background.astype(np.int)
    diff = balance_color(diff, percentile=1, separate_channels=False)
    diff = dilate(erode(diff, 3), 3)
    return diff
    _, otsu = cv2.threshold(diff, 0, 255,
                            cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return otsu == 255


def adaptive_threshold(img: np.ndarray, block_size: int, min_thresh: int):
    """
    Calculate a foreground mask based on adaptive thresholding.

    Decide which pixels are foreground pixels using the adaptive
    threshold algorithm.
    Each pixel is compared to its neighbouring pixels (size of this
    neighbourhood can be controlled with block_size) and if it has at
    least a value difference of min_thresh compared to the mean of the
    neighbourhood it will be considered part of the foreground,
    otherwise it will be background.

    Args:
        img: The image for which to calculate a foreground mask
        block_size: size of the neighbourhood around each pixel
        min_thresh: minimum difference from the mean of the neighbourhood

    Returns:
        The calculated foreground mask. If an element in the mask is
        False, this means that the corresponding pixel is part of the
        background. If it is True, the pixel is part of the foreground.

    """
    if img.ndim == 3:
        img = rgb_to_gray(img)

    # we want the background white, the foreground black
    # if that is not the case, flip black and white
    if np.median(img) < 100:
        img = 255 - img

    thresh = cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                   cv2.THRESH_BINARY, block_size, min_thresh)
    thresh_mask = thresh == 0
    return thresh_mask


def otsu_threshold(img: np.ndarray):
    """
    Calculate a foreground mask based on otsu thresholding.

    Decide which pixels are foreground pixels using the Otsu threshold
    algorithm

    Args:
        img: The image for which to calculate a foreground mask

    Returns:
        The calculated foreground mask. If an element in the mask is
        False, this means that the corresponding pixel is part of the
        background. If it is True, the pixel is part of the foreground.

    """
    if img.ndim == 3:
        img = rgb_to_gray(img)
    _, otsu = cv2.threshold(img, 0, 255,
                            cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return otsu == 0


def extract_background_colors(img: np.ndarray, thresh=0.4) -> np.ndarray:
    """
    Extract the most frequently occurring colors in an image

    Args:
        img: The image of shape (X, Y, 3) for which to extract the
            background color
        thresh: The threshold in percent that will be used to decide
            if a certain color is part of the background or not.
            If a color occurs at least thresh % as often as the most
            frequent color, it is considered part of the background.
            The default value is 40%.

    Returns:
        R, G, B color values of the background as numpy array of
        shape (N, 3). It is not guaranteed that the background colors
        actually occurs in the image, since the bit depth of the colors
        is reduced before extracting the most frequent ones.

    """
    assert 0 <= thresh <= 1
    # only use a subset of the colors of the image
    sample = _color_sample(img)
    # reduce bit depth
    mask = _generate_bitmask(2, 8)
    reduced_colors = sample & mask
    # combine r, g and b into one single value
    rgb = _pack_rgb_values(*[reduced_colors[:, i] for i in range(3)])
    # find the most frequent colors
    colors, counts = np.unique(rgb, return_counts=True)
    # find all the colors that occur at least thresh % as often as
    # the most frequent color. Those colors are the background colors
    # of the image
    most_frequent = counts.max()
    frequent_mask = (counts / most_frequent) >= thresh
    bg_colors = colors[frequent_mask]
    # convert back to separate r, g and b
    r, g, b = _unpack_rgb_values(bg_colors)
    bg_colors = np.stack([r, g, b], axis=1).astype(np.uint8)
    return bg_colors
